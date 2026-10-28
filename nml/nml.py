# ============================================================
# 手写语言 .nml 解释器 v0.3
# 作者：LiHangHai
#
# 用法：
#   python nml.py 程序.nml        运行一个 .nml 源文件
#   python nml.py                 进入交互模式（一行一个语句）
#
# 语法 v0.2：
#   文件头（不执行）：
#     file -> 名字        声明本文件名字
#     /*UTF-8*/           声明编码（块注释，自动跳过）
#   语句（以 ; 结尾）：
#     print(表达式);                打印
#     int var 变量 = 值;            首次声明变量（带类型）
#     var 变量 = 新值;              重新赋值（类型已定，不写类型）
#     var add 变量;                 变量自增 1（类似 a++）
#     var add 变量 数字;            变量加指定值（类似 a += 数字）
#     if (条件) -> { 语句... }      if 条件语句
#     while (条件) -> { 语句... }   while 循环（条件每轮重新判断）
#     for (终点, 步长, 起点) -> { 语句... }   for 计数循环
#       段1 终点、段2 步长、段3 起点，循环变量自动创建
#     int function 名字(参数) -> { 语句... }  函数定义
#       return 表达式;   返回并结束函数
#     函数调用：名字(实参)
#   import 包.子包;      导入库（从入口文件目录的 lib 加载）
#   package -> 包名      库文件包声明（不执行）
#   file -> 名字         文件头声明（不执行）
#   注释：/* ... */、/' ... '/ 块注释、// 行注释
#   表达式：
#     算术 + - * / 和括号，* / 优先，除法整数整除
#     比较 > < >= <= == !=（优先级最低）
#   块 { } 可以嵌套
#   安全：while 最多 100000 次，防止死循环
# ============================================================

import os
import sys

# ------------------------------------------------------------
# 第 1 步：分词器 tokenize
# token 格式：(类型, 内容)
#   类型 = 'NUM' | 'WORD' | 'OP'
# ------------------------------------------------------------
def tokenize(code):
    tokens = []
    i = 0
    n = len(code)
    while i < n:
        c = code[i]
        if c.isspace():                       # 空白跳过
            i += 1
            continue
        if c == '/' and i + 1 < n and code[i + 1] == '/':
            # 行注释 //：跳到行尾
            while i < n and code[i] != '\n':
                i += 1
            continue
        if c == '/' and i + 1 < n and code[i + 1] == "'":
            # 块注释 /' ... '/：跳到 '/ 之后
            i += 2
            closed = False
            while i + 1 < n:
                if code[i] == "'" and code[i + 1] == '/':
                    closed = True
                    break
                i += 1
            if not closed:
                raise SyntaxError("注释没闭合，缺少 '/")
            i += 2
            continue
        if c == '/' and i + 1 < n and code[i + 1] == '*':
            # 块注释 /* ... */：跳到 */ 之后（注释头旧语法）
            i += 2
            closed = False
            while i + 1 < n:
                if code[i] == '*' and code[i + 1] == '/':
                    closed = True
                    break
                i += 1
            if not closed:
                raise SyntaxError('注释没闭合，缺少 */')
            i += 2
            continue
        if c == '<' and i + 2 < n and code[i + 1] == '-' and code[i + 2] == '>':
            tokens.append(('OP', '<->'))       # <-> 连接函数第二参数组
            i += 3
            continue
        if c == '-':
            if i + 1 < n and code[i + 1] == '>':
                tokens.append(('OP', '->'))       # 箭头（if/while/file 用）
                i += 2
                continue
            # 也可能是 '-' 普通减号，落到下面符号分支
        if c == '"':                            # 字符串字面量 "..." 
            i += 1
            s = ''
            while i < n and code[i] != '"':
                s += code[i]
                i += 1
            if i >= n:
                raise SyntaxError('字符串没闭合')
            i += 1
            tokens.append(('STR', s))
            continue
        if c.isdigit():                       # 数字（整数）
            num = ''
            while i < n and code[i].isdigit():
                num += code[i]
                i += 1
            tokens.append(('NUM', int(num)))
            continue
        if c.isalpha() or c == '_':           # 名字 / 关键字
            word = ''
            while i < n and (code[i].isalnum() or code[i] == '_'):
                word += code[i]
                i += 1
            tokens.append(('WORD', word))
            continue
        if c in '+-*/()=;{},.<>:!%[]':        # 运算符和符号（含逗号、点号、冒号、取模、下标）
            two = c + (code[i + 1] if i + 1 < n else '')
            if two in ('==', '!=', '>=', '<=', '<-', '::'):   # 双字符运算符（含 <- 步长箭头、:: 实例化）
                tokens.append(('OP', two))
                i += 2
                continue
            tokens.append(('OP', c))
            i += 1
            continue
        raise SyntaxError(f'无法识别的字符 “{c}”')
    return tokens


# ------------------------------------------------------------
# 第 2 步：解释器（流式解析：语句 + 块递归）
# ------------------------------------------------------------
class ReturnSignal(Exception):
    """函数里遇到 return 时抛出，携带返回值，用来中断函数并返回值"""
    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    """循环里遇到 break 时抛出，用来跳出当前循环"""


class ApiRandom:
    """内置 API：windows.random（对接 Python random）"""
    def __init__(self):
        self.max = None            # 随机范围上限
        self.min = None            # 随机范围下限
    def new(self, args):
        import random
        if not args or args[0] != 'int':
            raise TypeError('windows.random::new 只支持生成 "int"')
        return random.randint(self.min, self.max)


class ApiInput:
    """内置 API：windows.input（读取控制台输入）"""
    def __init__(self):
        self.__dict__['value'] = None      # 读到的输入值
        self.__dict__['break'] = False     # 是否已有输入可读
    def run(self):
        import sys
        line = sys.stdin.readline()        # 阻塞读一行
        self.__dict__['value'] = line.rstrip('\n')
        self.__dict__['break'] = True


class NML:
    def __init__(self, tokens, funcs=None, lib_root=None, imported=None, is_lib=False, apis=None):
        self.tokens = tokens
        self.pos = 0              # 游标
        self.env = {}             # 变量表（扁平作用域）
        self.funcs = funcs if funcs is not None else {}   # 函数表
        self.lib_root = lib_root                            # 库根目录
        self.imported = imported if imported is not None else set()  # 已导入库
        self.namespace = None     # 当前命名空间（库文件用）
        self.is_lib = is_lib      # 是否为库文件（函数带命名空间注册）
        self.apis = apis if apis is not None else {}  # 内置 API 对象表（如 windows.random）

    def run_all(self):
        while self.pos < len(self.tokens):
            self.parse_statement()

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def peek_next(self):
        if self.pos + 1 < len(self.tokens):
            return self.tokens[self.pos + 1]
        return None

    def peek_third(self):
        if self.pos + 2 < len(self.tokens):
            return self.tokens[self.pos + 2]
        return None

    def next(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect_op(self, op):
        if self.pos >= len(self.tokens):
            raise SyntaxError(f'期望 “{op}”，但到了文件结尾')
        t = self.next()
        if t != ('OP', op):
            raise SyntaxError(f'期望 “{op}”，但得到 {t}')

    def expect_word(self, w):
        t = self.next()
        if t != ('WORD', w):
            raise SyntaxError(f'期望 “{w}”，但得到 {t}')

    def require_name(self):
        if self.pos >= len(self.tokens):
            raise SyntaxError('这里需要变量名，但到了文件结尾')
        t = self.next()
        if t[0] != 'WORD':
            raise SyntaxError('这里需要变量名')
        return t[1]

    def check_var(self, name):
        if name not in self.env:
            raise NameError(f'变量 “{name}” 还没声明')

    # ---------- 打印值（实例对象输出类名） ----------
    def print_value(self, value):
        if isinstance(value, tuple) and len(value) == 2 and value[0] == 'instance':
            print(value[1])                      # 实例输出类名
        elif isinstance(value, list):            # 数组输出 [1, 2, 3]
            print('[' + ', '.join(str(x) for x in value) + ']')
        else:
            print(value)

    # ---------- 表达式（比较最低，加减其次，乘除最高） ----------
    def parse_expr(self):                      # 比较级
        value = self.parse_add()
        while True:
            t = self.peek()
            if t and t[0] == 'OP' and t[1] in ('>', '<', '>=', '<=', '==', '!='):
                self.next()
                rhs = self.parse_add()
                if   t[1] == '>':  value = value > rhs
                elif t[1] == '<':  value = value < rhs
                elif t[1] == '>=': value = value >= rhs
                elif t[1] == '<=': value = value <= rhs
                elif t[1] == '==': value = value == rhs
                else:              value = value != rhs
            else:
                return value

    def parse_add(self):                       # 加减级
        value = self.parse_term()
        while True:
            t = self.peek()
            if t == ('OP', '+'):
                self.next()
                value = value + self.parse_term()
            elif t == ('OP', '-'):
                self.next()
                value = value - self.parse_term()
            else:
                return value

    def parse_term(self):                      # 乘除级
        value = self.parse_atom()
        while True:
            t = self.peek()
            if t == ('OP', '*'):
                self.next()
                value = value * self.parse_atom()
            elif t == ('OP', '/'):
                self.next()
                rhs = self.parse_atom()
                if rhs == 0:
                    raise RuntimeError('除数不能为 0')
                value = value // rhs
            elif t == ('OP', '%'):
                self.next()
                rhs = self.parse_atom()
                if rhs == 0:
                    raise RuntimeError('取模的除数不能为 0')
                value = value % rhs
            else:
                return value

    def parse_atom(self):                      # 最基础单元
        t = self.next()
        if t == ('OP', '-'):                   # 一元负号（如 -1、-x）
            return -self.parse_atom()
        if t == ('WORD', 'new'):               # new 类(实参) 实例化
            return self.parse_new()
        if t == ('WORD', 'setList'):           # setList(下标,值) <- 数组：改列表值
            return self.parse_setlist()
        if t[0] == 'STR':                      # 字符串字面量（需已导入 type.string 库）
            if 'type.string' not in self.imported:
                raise NameError('使用字符串需要先 import type.string')
            return t[1]
        if t[0] == 'NUM':
            return t[1]
        if t[0] == 'WORD':
            name = t[1]
            while self.peek() == ('OP', '.'):      # 命名空间/成员路径 a.b.c
                self.next()                        # 吃 .
                nxt = self.peek()
                if nxt and nxt[0] == 'WORD':
                    first = name.split('.')[0]
                    if first in self.env and isinstance(self.env[first], tuple) \
                            and len(self.env[first]) == 2 and self.env[first][0] == 'instance':
                        name = self.env[first][1] + '.' + nxt[1]  # 实例变量 → 用实例类名
                    else:
                        name = name + '.' + nxt[1]
                    self.next()
                else:
                    raise SyntaxError('点号后需要名字')
            if self.peek() == ('OP', '::'):         # 实例化 / 内置 API 方法
                return self.parse_instance(None, name)
            if self.peek() == ('OP', '('):         # 函数调用 名字(实参)
                value = self.call_function(name)
                if self.peek() == ('OP', '::'):    # 后面跟 ::new() 实例化
                    return self.parse_instance(value, name)
                return value
            if self.peek() == ('OP', ':'):         # 强转 类型:值
                self.next()
                value = self.parse_atom()
                return self.force_cast(name, value)
            # 内置 API 对象属性/方法：windows.input.value / windows.input.run(...)
            if '.' in name:
                parts = name.split('.')
                for i in range(len(parts) - 1, 0, -1):
                    obj = '.'.join(parts[:i])
                    if obj in self.apis:
                        attr = parts[i]
                        if self.peek() == ('OP', '('):   # API 方法调用
                            self.next()
                            margs = []
                            if self.peek() != ('OP', ')'):
                                while True:
                                    margs.append(self.parse_expr())
                                    if self.peek() == ('OP', ','):
                                        self.next()
                                        continue
                                    break
                            self.expect_op(')')
                            return getattr(self.apis[obj], attr)(*margs)
                        return getattr(self.apis[obj], attr)   # API 属性读取
            if name in self.env:                   # 变量
                value = self.env[name]
                if self.peek() == ('OP', '['):     # 数组下标 a[i]
                    self.next()
                    idx = self.parse_expr()
                    self.expect_op(']')
                    if not isinstance(value, list):
                        raise TypeError(f'“{name}” 不是数组，不能下标访问')
                    if idx < 0 or idx >= len(value):
                        raise IndexError(f'下标 {idx} 越界（数组长度 {len(value)}）')
                    return value[idx]
                return value
            raise NameError(f'变量 “{name}” 还没声明')
        if t == ('OP', '('):
            value = self.parse_expr()
            self.expect_op(')')
            return value
        raise SyntaxError(f'表达式里出现不该有的东西 {t}')

    # ---------- 语句 ----------
    def parse_statement(self):
        t = self.peek()
        if t is None:
            return
        if t == ('WORD', 'print'):
            self.next()
            self.expect_op('(')
            value = self.parse_expr()
            self.expect_op(')')
            self.expect_op(';')
            self.print_value(value)
        elif t == ('WORD', 'class'):
            self.parse_class()
        elif t == ('WORD', 'int'):
            self.next()
            if self.peek() == ('WORD', 'var'):        # int var 变量 = 值（首次声明）
                self.next()
                name = self.require_name()
                self.expect_op('=')
                value = self.parse_expr()
                self.expect_op(';')
                self.env[name] = value
            elif self.peek() == ('WORD', 'function'): # int function 函数定义
                self.parse_function()
            else:
                raise SyntaxError(f'int 后面要么是 var 声明，要么是 function 定义，但得到 {self.peek()}')
        elif t == ('WORD', 'var'):
            self.next()
            if self.peek() == ('OP', '.'):         # 命名空间 var.xxx(...)
                name = self.parse_dotted_suffix('var')
                if self.peek() != ('OP', '('):
                    raise SyntaxError(f'命名空间 “{name}” 不是函数调用')
                self.call_function(name)
                self.expect_op(';')
            elif self.peek() == ('WORD', 'add'):   # var add 变量 [数字]
                self.next()
                name = self.require_name()
                self.check_var(name)
                if self.peek() == ('OP', ';'):     # 无数字 → 自增 1
                    self.next()
                    self.env[name] = self.env[name] + 1
                else:                              # 有数字 → 加指定值
                    num = self.parse_expr()
                    self.expect_op(';')
                    self.env[name] = self.env[name] + num
            else:                                  # var 变量 = 值（重新赋值）
                name = self.require_name()
                self.check_var(name)
                self.expect_op('=')
                value = self.parse_expr()
                self.expect_op(';')
                self.env[name] = value
        elif t == ('WORD', 'if'):
            self.parse_if()
        elif t == ('WORD', 'while'):
            self.parse_while()
        elif t == ('WORD', 'for'):
            self.parse_for()
        elif t == ('WORD', 'return'):
            self.next()
            value = self.parse_expr()
            self.expect_op(';')
            raise ReturnSignal(value)          # 中断函数并返回
        elif t == ('WORD', 'break'):           # 跳出当前循环
            self.next()
            self.expect_op(';')
            raise BreakSignal()
        elif t == ('WORD', 'run'):             # run (代码块)：执行一段代码
            self.next()
            self.expect_op('(')
            code_val = self.parse_expr()
            self.expect_op(')')
            self.expect_op(';')
            try:
                self.run_code(code_val)
            except ReturnSignal as r:
                raise r                        # 块的 return 传播给所在函数（block sleep 返回）
        elif t == ('WORD', 'file'):            # 文件头：file -> 名字（不执行）
            self.next()
            if self.peek() == ('OP', '->'):
                self.next()
                self.namespace = self.parse_dotted_name()
        elif t == ('WORD', 'package'):         # 包声明：package -> 包名（不执行）
            self.next()
            if self.peek() == ('OP', '->'):
                self.next()
                self.parse_dotted_name()
        elif t == ('WORD', 'import'):          # 导入库：import 包.子包;
            self.next()
            path = self.parse_dotted_name()
            self.expect_op(';')
            self.load_import(path)
        elif t == ('WORD', 'void'):            # void function / void block 函数定义
            self.next()
            if self.peek() == ('WORD', 'function'):
                self.parse_function()
            elif self.peek() == ('WORD', 'block'):
                self.parse_function(is_block=True)   # parse_function 内部会吃掉 block
            else:
                raise SyntaxError(f'void 后面应该是 function 或 block，但得到 {self.peek()}')
        elif t == ('WORD', 'String'):          # String var 声明 / String function 函数
            self.next()
            if self.peek() == ('WORD', 'var'):        # String var 变量 = 值
                self.next()
                name = self.require_name()
                self.expect_op('=')
                value = self.parse_expr()
                self.expect_op(';')
                self.env[name] = value
            elif self.peek() == ('WORD', 'function'): # String function 函数定义
                self.parse_function()
            else:
                raise SyntaxError(f'String 后面要么是 var 声明，要么是 function 定义，但得到 {self.peek()}')
        elif t[0] == 'WORD' and t[1] and t[1][0].isupper() and self.peek_next() == ('WORD', 'var'):
            # 对象类型声明：Q var 名字 = 值（大写 = 类对象类型，如 Q/Var）
            self.next()                        # 吃类型 Q
            self.next()                        # 吃 var
            name = self.require_name()
            self.expect_op('=')
            value = self.parse_expr()
            self.expect_op(';')
            self.env[name] = value
        elif t == ('WORD', 'intList') and self.peek_next() == ('WORD', 'var'):
            # intList var 数组声明
            self.next()                        # 吃 intList
            self.next()                        # 吃 var
            name = self.require_name()
            self.expect_op('=')
            value = self.parse_expr()
            self.expect_op(';')
            self.env[name] = value
        elif t[0] == 'WORD' and self.peek_next() == ('OP', '['):
            # 数组下标赋值：变量[下标] = 值;
            name = t[1]
            self.next()                      # 吃 变量名
            self.next()                      # 吃 [
            idx = self.parse_expr()
            self.expect_op(']')
            self.check_var(name)
            arr = self.env[name]
            if not isinstance(arr, list):
                raise TypeError(f'“{name}” 不是数组，不能下标赋值')
            self.expect_op('=')
            value = self.parse_expr()
            self.expect_op(';')
            if idx < 0 or idx >= len(arr):
                raise IndexError(f'下标 {idx} 越界（数组长度 {len(arr)}）')
            arr[idx] = value
        else:
            if t and t[0] == 'WORD':
                # 内置 API 对象属性赋值：windows.random.max = 值;
                save = self.pos
                self.next()                    # 吃第一个名字
                parts = [t[1]]
                while self.peek() == ('OP', '.'):
                    self.next()
                    nxt = self.peek()
                    if nxt and nxt[0] == 'WORD':
                        parts.append(nxt[1])
                        self.next()
                    else:
                        break
                matched = False
                for i in range(len(parts) - 1, 0, -1):
                    obj = '.'.join(parts[:i])
                    if obj in self.apis:
                        if self.peek() == ('OP', '='):
                            self.next()
                            val = self.parse_expr()
                            self.expect_op(';')
                            setattr(self.apis[obj], parts[i], val)
                        else:
                            # API 方法/属性触发：windows.input.run;
                            api = self.apis[obj]
                            attr = getattr(api, parts[i])
                            if callable(attr):
                                attr()         # 调用方法（如 run 触发读取）
                            self.expect_op(';')
                        matched = True
                        break
                if matched:
                    return
                self.pos = save                 # 回退，按函数调用处理
                # 函数调用语句：名字(实参) 或 命名空间.函数(实参)
                if self.peek_next() == ('OP', '(') or self.peek_next() == ('OP', '.'):
                    ret = self.parse_atom()          # 走 call_function（含点号路径）
                    if self.peek() == ('OP', ';'):
                        self.next()
                    elif not self._block_call:
                        raise SyntaxError('期望 “;”，但到了文件结尾')
                    # 块调用返回值传播为函数返回值（函数体内）
                    if self._block_call and ret is not None and getattr(self, '_in_function', False):
                        raise ReturnSignal(ret)
                    return
            raise SyntaxError(f'不认识的开头 {t}')

    # ---------- if：if (条件) -> { 块 } ----------
    def parse_if(self):
        self.next()                            # 吃掉 if
        self.expect_op('(')
        cond = self.parse_expr()
        self.expect_op(')')
        if self.peek() == ('OP', '->'):        # 箭头可选：int function f() -> { } 或 int function f() { }
            self.next()
        self.expect_op('{')
        if cond:
            self.parse_block_body()
        else:
            self.skip_block_body()
        # else 分支：else -> { 块 }
        if self.peek() == ('WORD', 'else'):
            self.next()
            if self.peek() == ('OP', '->'):
                self.next()
            self.expect_op('{')
            if not cond:
                self.parse_block_body()
            else:
                self.skip_block_body()

    # ---------- while：while (条件) -> { 块 } ----------
    def parse_while(self):
        self.next()                            # 吃掉 while
        self.expect_op('(')
        cond_start = self.pos                  # 条件 token 起点
        self.parse_expr()                      # 先验证语法
        cond_end = self.pos                    # 条件 token 终点
        self.expect_op(')')
        if self.peek() == ('OP', '->'):        # 箭头可选：int function f() -> { } 或 int function f() { }
            self.next()
        self.expect_op('{')
        body_start = self.pos                  # 块内容起点
        count = 0
        while True:
            self.pos = cond_start              # 每轮拨回条件开头重新求值
            cond = self.parse_expr()
            self.pos = cond_end
            if not cond:                       # 条件为假：跳过块，结束
                self.pos = body_start
                self.skip_block_body()
                break
            self.pos = body_start              # 执行一轮块体
            try:
                self.parse_block_body()
            except BreakSignal:               # break：跳出循环
                self.pos = body_start
                self.skip_block_body()
                break
            count += 1
            if count > 100000:
                raise RuntimeError('while 循环超过 100000 次，疑似死循环')

    # ---------- for：for (终点, 步长, 起点) -> { 块 } ----------
    # 段1 = 终点，段2 = 步长，段3 = 起点；循环变量自动创建
    def parse_for(self):
        self.next()                                # 吃掉 for
        self.expect_op('(')
        name1, val1 = self.parse_for_segment()     # 第一段
        if self.peek() == ('OP', ','):
            # 三段式：终点, 步长, 起点
            self.next()
            name_step, step = self.parse_for_segment() # 段2 步长
            self.expect_op(',')
            name_start, start = self.parse_for_segment() # 段3 起点
            self.expect_op(')')
            if self.peek() == ('OP', '->'):        # 箭头可选
                self.next()
            self.expect_op('{')
            body_start = self.pos
            var = name1 or name_step or 'i'        # 循环变量名
            self.env[var] = start                  # 自动创建，赋起点
            count = 0
            while True:
                cur = self.env[var]
                if step >= 0:
                    if cur > val1:
                        break
                else:
                    if cur < val1:
                        break
                self.pos = body_start               # 执行一轮块体
                try:
                    self.parse_block_body()
                except BreakSignal:               # break：跳出循环
                    self.pos = body_start
                    self.skip_block_body()
                    break
                count += 1
                if count > 100000:
                    raise RuntimeError('for 循环超过 100000 次，疑似死循环')
                self.env[var] = self.env[var] + step
        else:
            # 遍历：for (i <- 数组) 或 for (code codeLine <- 代码块)
            self.expect_op(')')
            if self.peek() == ('OP', '->'):        # 箭头可选
                self.next()
            self.expect_op('{')
            body_start = self.pos
            var = name1 or 'i'
            arr = val1
            if isinstance(arr, list) and arr and all(isinstance(x, tuple) and len(x) == 2 for x in arr):
                items = self.split_code_lines(arr)   # code 代码块：按语句遍历
            elif isinstance(arr, list):
                items = arr                          # 数组：逐元素
            else:
                raise TypeError(f'for 遍历目标 “{arr}” 不是数组或代码块')
            count = 0
            for item in items:
                self.env[var] = item
                self.pos = body_start
                try:
                    self.parse_block_body()
                except BreakSignal:               # break：跳出循环
                    self.pos = body_start
                    self.skip_block_body()
                    break
                count += 1
                if count > 100000:
                    raise RuntimeError('for 循环超过 100000 次，疑似死循环')

    def parse_for_segment(self):
        # 每段：可选 "变量 -> 值" / "变量 <- 值" / "类型 变量 <- 值" / 纯 "值"
        name = None
        t = self.peek()
        if t and t[0] == 'WORD':
            nxt = self.peek_next()
            if nxt in (('OP', '->'), ('OP', '<-')):
                name = t[1]
                self.next()                        # 变量名
                self.next()                        # -> 或 <-
            elif nxt and nxt[0] == 'WORD' and self.peek_third() in (('OP', '->'), ('OP', '<-')):
                # 类型 变量 <- 值（如 code codeLine <- code）
                self.next()                        # 吃 类型
                name = self.require_name()         # 变量名
                self.next()                        # 吃 -> 或 <-
        value = self.parse_expr()
        return name, value

    # ---------- 函数定义：int function 名字(参数) -> { 块 } ----------
    def parse_function(self, class_prefix=None, is_block=False):
        self.next()                            # 吃掉 function（或 block 已被外部吃掉）
        name = self.require_name()             # 函数名
        params = self.parse_params()           # 参数列表 [(类型, 名字, 默认值)]
        if self.peek() == ('OP', '->'):        # 箭头可选：int function f() -> { } 或 int function f() { }
            self.next()
        self.expect_op('{')
        body_start = self.pos                  # 函数体起点（'{' 后）
        self.skip_block_body()                 # 跳过函数体到 '}' 后
        body_end = self.pos - 1                # 去掉收尾的 '}'
        if is_block:
            full_name = name                   # block 函数不带命名空间前缀，可直接调用
        else:
            full_name = (self.namespace + '.' if self.is_lib and self.namespace else '') + (class_prefix + '.' if class_prefix else '') + name
        self.funcs.setdefault(full_name, []).append((params, self.tokens[body_start:body_end]))

    # ---------- 参数列表：(...) (...) 或 (...) <-> (...) 多组参数 ----------
    def parse_params(self):
        params = []
        self.parse_param_group(params)
        while self.peek() == ('OP', '(') or self.peek() == ('OP', '<->'):
            if self.peek() == ('OP', '<->'):   # <-> 可选连接符
                self.next()
            self.parse_param_group(params)
        return params

    def parse_param_group(self, params):
        self.expect_op('(')
        if self.peek() != ('OP', ')'):
            while True:
                self.parse_param(params)
                if self.peek() == ('OP', ','):
                    self.next()
                    continue
                break
        self.expect_op(')')

    def parse_param(self, params):
        ptype = self.require_name()            # 参数类型
        if self.peek() in (('OP', '->'), ('OP', '=')):   # code -> "X"：无名字，名字=默认值去引号
            self.next()
            default = self.parse_expr()
            pname = default if isinstance(default, str) else ptype
            params.append((ptype, pname, default))
            return
        pname = self.require_name()            # 参数名
        default = None
        if self.peek() in (('OP', '->'), ('OP', '=')):   # 可选默认值：类型 名字 -> 值
            self.next()
            default = self.parse_expr()
        params.append((ptype, pname, default))

    # ---------- 类定义：class 名字 -> { 方法... } ----------
    def parse_class(self):
        self.next()                            # 吃 class
        cname = self.require_name()            # 类名
        self.expect_op('->')
        self.expect_op('{')
        while self.peek() != ('OP', '}'):      # 解析类内方法直到 }
            t = self.peek()
            if t and t[0] == 'WORD' and self.peek_next() == ('WORD', 'function'):
                self.next()                    # 吃返回类型（int/void/String 等）
                self.parse_function(cname)
            else:
                raise SyntaxError(f'类里应该是方法定义，但得到 {self.peek()}')
        self.expect_op('}')

    # ---------- ::new() 实例化：触发同名构造函数 ----------
    def parse_instance(self, value, dotted_name):
        self.expect_op('::')
        self.expect_word('new')
        self.expect_op('(')
        args = []
        if self.peek() != ('OP', ')'):
            while True:
                args.append(self.parse_expr())
                if self.peek() == ('OP', ','):
                    self.next()
                    continue
                break
        self.expect_op(')')
        if dotted_name in self.apis:           # 内置 API 对象方法调用
            return self.apis[dotted_name].new(args)
        cls = dotted_name.split('.')[0]        # 类名 = 点号前部分
        ctor = cls + '.' + cls                 # 构造函数 = 类名.类名（与类同名）
        params, body = self.find_func(ctor, [])  # 匹配 0 参构造函数（::new() 无参）
        sub = NML(body, self.funcs, self.lib_root, self.imported, False, apis=self.apis)
        sub.run_all()                          # 执行构造函数体（副作用，如 print）
        return value                           # 实例化不改变值

    # ---------- new 类(实参) 实例化 ----------
    def parse_new(self):
        cls = self.require_name()              # 类名
        ctor = cls + '.' + cls                 # 构造函数 = 类名.类名
        self.expect_op('(')
        args = []
        if self.peek() != ('OP', ')'):
            while True:
                args.append(self.parse_expr())
                if self.peek() == ('OP', ','):
                    self.next()
                    continue
                break
        self.expect_op(')')
        if cls == 'intList':                 # 内置整数数组类型
            return list(args)                # new intList(1,2,3) → [1,2,3]
        params, body = self.find_func(ctor, args)  # 按实参匹配构造函数（个数+类型）
        local = {}                             # 绑定参数到局部环境
        for (pt, pn, _), av in zip(params, args):
            local[pn] = av
        sub = NML(body, self.funcs, self.lib_root, self.imported, False, apis=self.apis)
        sub.env = local
        sub.run_all()                          # 执行构造函数副作用
        return ('instance', cls)               # 实例对象（类名标记，print 输出类名）

    # ---------- setList(下标,值) <- 数组：改列表值（返回新数组） ----------
    def parse_setlist(self):
        self.expect_op('(')
        idx = self.parse_expr()
        self.expect_op(',')
        nv = self.parse_expr()
        self.expect_op(')')
        self.expect_op('<-')
        arr = self.parse_atom()
        if not isinstance(arr, list):
            raise TypeError('setList 只能用于数组')
        if idx < 0 or idx >= len(arr):
            raise IndexError(f'下标 {idx} 越界（数组长度 {len(arr)}）')
        newarr = list(arr)                     # 返回新数组，不改原数组
        newarr[idx] = nv
        return newarr

    # ---------- 点分名字：a.b.c ----------
    def parse_dotted_name(self):
        parts = []
        t = self.next()
        if t[0] != 'WORD':
            raise SyntaxError('期望包名/名字')
        parts.append(t[1])
        while self.peek() == ('OP', '.'):
            self.next()
            t = self.next()
            if t[0] != 'WORD':
                raise SyntaxError('期望包名/名字')
            parts.append(t[1])
        return '.'.join(parts)

    # ---------- 点分后缀：当前在 '.'，拼接 .名字 到 base ----------
    def parse_dotted_suffix(self, base):
        while self.peek() == ('OP', '.'):
            self.next()                      # 吃 .
            nxt = self.next()
            if nxt[0] != 'WORD':
                raise SyntaxError('点号后需要名字')
            base = base + '.' + nxt[1]
        return base

    # ---------- 导入库：import 包.子包; ----------
    def load_import(self, path):
        if path in self.imported:              # 已导入过，跳过（防重复/循环）
            return
        self.imported.add(path)
        if path.startswith('api.'):            # 内置 API 库（无本地文件）
            self.load_api(path)
            return
        if not self.lib_root:
            raise ImportError('未设置库根目录，无法导入')
        rel = path.replace('.', os.sep) + '.nml'
        file_path = os.path.join(self.lib_root, rel)
        if not os.path.exists(file_path):
            raise ImportError(f'找不到库 “{path}”（{file_path}）')
        with open(file_path, encoding='utf-8') as f:
            source = f.read()
        sub = NML(tokenize(source), self.funcs, self.lib_root, self.imported, is_lib=True, apis=self.apis)
        sub.run_all()                          # 解析 package、递归 import、函数定义

    # ---------- 内置 API：import api.xxx ----------
    def load_api(self, path):
        if path == 'api.windows.random':
            self.apis['windows.random'] = ApiRandom()
        elif path == 'api.windows.input':
            self.apis['windows.input'] = ApiInput()
        else:
            raise ImportError(f'未知内置 API “{path}”')

    # ---------- 按实参匹配函数版本（重载：个数+类型） ----------
    def find_func(self, name, args):
        if name not in self.funcs:
            raise NameError(f'函数 “{name}” 未定义')
        versions = self.funcs[name]
        count_match = [v for v in versions if len(v[0]) == len(args)]
        if not count_match:
            need = ' / '.join(str(len(v[0])) for v in versions)
            raise TypeError(f'函数 “{name}” 需要 {need} 个参数，给了 {len(args)}')
        for params, body in count_match:
            if all(self.type_matches(pt, av) for (pt, pn, _), av in zip(params, args)):
                return params, body
        raise TypeError(f'函数 “{name}” 没有匹配参数类型的版本（实参 {args}）')

    # ---------- 参数类型是否匹配实参 ----------
    def type_matches(self, ptype, value):
        if ptype in ('new', 'all'):        # 未知/任意类型
            return True
        if ptype == 'int':
            return isinstance(value, int)
        if ptype in ('string', 'String'):
            return isinstance(value, str)
        return True                        # 其他类型默认宽松匹配

    # ---------- 函数调用：名字(实参) ----------
    def call_function(self, name):
        self._block_call = False             # 本次是否块调用（带 { } 代码块）
        self.expect_op('(')
        args = []                              # 实参值列表
        if self.peek() != ('OP', ')'):
            while True:
                args.append(self.parse_expr())
                if self.peek() == ('OP', ','):
                    self.next()
                    continue
                break
        self.expect_op(')')
        # 块参数：{ 代码 } 和 code { 代码 }（code 类型参数）
        while True:
            t = self.peek()
            if t == ('OP', '{'):               # { 代码块 }
                args.append(self.parse_code_block())
                self._block_call = True
                continue
            if t == ('WORD', 'code') and self.peek_next() == ('OP', '{'):
                self.next()                    # 吃 code
                args.append(self.parse_code_block())
                self._block_call = True
                continue
            break
        params, body = self.find_func(name, args)
        local = {}                             # 局部环境：参数名 -> 实参值
        for (pt, pn, _), av in zip(params, args):
            local[pn] = av
        # 未显式传值的参数用默认值
        for (pt, pn, default) in params[len(args):]:
            local[pn] = default
        sub = NML(body, self.funcs, self.lib_root, self.imported, False, apis=self.apis)            # 子解释器执行函数体，共享函数表
        sub.env = local
        sub._in_function = True              # 标记：函数体里块调用返回值传播为函数返回
        try:
            sub.run_all()
            return None                        # 没 return 则返回空
        except ReturnSignal as r:
            return r.value

    # ---------- 代码块参数：{ ... } 解析为 token 列表 ----------
    def parse_code_block(self):
        self.expect_op('{')
        start = self.pos
        self.skip_block_body()                 # 跳到匹配 '}' 后
        end = self.pos - 1                     # 去掉收尾 '}'
        return self.tokens[start:end]          # code 值 = token 列表

    # ---------- run(代码)：执行一段代码 ----------
    def run_code(self, code_val):
        if isinstance(code_val, str):
            code_tokens = tokenize(code_val)
        else:
            code_tokens = code_val
        sub = NML(code_tokens, self.funcs, self.lib_root, self.imported, False, apis=self.apis)
        try:
            sub.run_all()
            return None
        except ReturnSignal as r:
            raise r                          # 块里的 return 重新抛出，传播给所在函数

    # ---------- 把代码 token 按语句分割（每句到 ;） ----------
    def split_code_lines(self, tokens):
        lines = []
        cur = []
        depth = 0
        for t in tokens:
            if t == ('OP', '{'):
                depth += 1
            elif t == ('OP', '}'):
                depth -= 1
                if depth < 0:
                    break
            cur.append(t)
            if t == ('OP', ';') and depth == 0:
                lines.append(cur)
                cur = []
        if cur:
            lines.append(cur)
        return lines

    # ---------- 强制类型转换：类型:值 ----------
    def force_cast(self, typename, value):
        if typename == 'String':
            return str(value)
        if typename == 'int':
            return int(value)
        raise TypeError(f'不支持的类型转换 “{typename}”')

    # ---------- 块体：执行到 } ----------
    def parse_block_body(self):
        while True:
            t = self.peek()
            if t is None:
                raise SyntaxError('块没闭合，缺少 }')
            if t == ('OP', '}'):
                self.next()
                return
            self.parse_statement()

    # ---------- 跳过块体（条件为假时不执行） ----------
    def skip_block_body(self):
        depth = 1                              # 当前已站在块内
        while depth > 0:
            t = self.next()
            if t is None:
                raise SyntaxError('块没闭合，缺少 }')
            if t == ('OP', '{'):
                depth += 1
            elif t == ('OP', '}'):
                depth -= 1


# ------------------------------------------------------------
# 第 3 步：运行完整源码（含文件头）
# ------------------------------------------------------------
def run(source, source_path=None):
    tokens = tokenize(source)
    lib_root = None
    if source_path:
        lib_root = os.path.join(os.path.dirname(os.path.abspath(source_path)), 'lib')
    nml = NML(tokens, lib_root=lib_root)
    if tokens and tokens[0] == ('WORD', 'file'):
        nml.next()
        if nml.peek() == ('OP', '->'):
            nml.next()
        if nml.peek() and nml.peek()[0] == 'WORD':
            nml.next()
    nml.run_all()


def main():
    if len(sys.argv) >= 2:
        with open(sys.argv[1], encoding='utf-8') as f:
            source = f.read()
        try:
            run(source, sys.argv[1])
        except Exception as e:
            print(f'错误: {e}')
    else:
        print('手写语言 .nml v0.3 交互模式，输入 退出 结束（函数/块语句请写进文件运行）')
        env_holder = {'env': {}}
        while True:
            line = input('nml> ')
            if line.strip() == '退出':
                break
            try:
                nml = NML(tokenize(line))
                nml.env = env_holder['env']
                while nml.pos < len(nml.tokens):
                    nml.parse_statement()
            except Exception as e:
                print(f'错误: {e}')


if __name__ == '__main__':
    main()
