#! /usr/bin/env python3

import os
import sys
import threading
import traceback
import collections

import urwid

class FancyEdit(urwid.ListBox):
    signals = ["change"]

    def __init__(self, text):
        self.lines = []
        self.edit_text = text
        self.changed = False
        super().__init__(self.lines)
        self.cut_list = []
        self.last_cut_pos = None

    def _make_line_editor(self, text):
        text = text.expandtabs(4)
        editor = urwid.Edit(edit_text=text, wrap='clip', edit_pos=0)
        def emit_change(subedit, text):
            if subedit.edit_text != text:
                self.changed = True
        urwid.connect_signal(editor, 'change', emit_change)
        return editor

    @property
    def edit_text(self):
        return '\n'.join(e.edit_text for e in self.lines)

    @edit_text.setter
    def edit_text(self, new_text):
        self.lines[:] = [self._make_line_editor(l)
            for l in new_text.splitlines() + ['']]

    def keypress(self, size, key):
        if key == 'backspace':
            widget, pos = self.get_focus()
            head = widget.edit_text[:widget.edit_pos]
            if head and not head.strip():
                key = 'shift tab'
        elif key == 'home':
            widget, pos = self.get_focus()
            if widget.edit_pos == 0:
                key = 'smart home'
        key = super().keypress(size, key)
        return_value = None
        if key == 'left':
            widget, pos = self.get_focus()
            if pos > 0:
                self.set_focus(pos - 1)
                widget, pos = self.get_focus()
                self.keypress(size, 'end')
        elif key == 'right':
            widget, pos = self.get_focus()
            widget.set_edit_pos(0)
            self.set_focus(pos + 1)
        elif key == 'tab':
            widget, pos = self.get_focus()
            old_pos = widget.edit_pos
            widget.set_edit_pos(0)
            widget.insert_text(' ' * 4)
            widget.set_edit_pos(old_pos + 4)
        elif key == 'shift tab':
            widget, pos = self.get_focus()
            old_pos = widget.edit_pos
            for i in range(4):
                if widget.edit_text.startswith(' '):
                    widget.set_edit_pos(widget.edit_pos - 1)
                    widget.edit_text = widget.edit_text[1:]
        elif key == 'enter':
            widget, pos = self.get_focus()
            orig_line = widget.edit_text
            split_point = widget.edit_pos
            head, tail = orig_line[:split_point], orig_line[split_point:]
            widget.edit_text = head
            tail = tail.lstrip()
            self.lines[pos + 1:pos + 1] = [self._make_line_editor(tail)]
            self.keypress(size, 'down')
            widget, pos = self.get_focus()
            widget.edit_pos = 0
            while orig_line.startswith(' ' * 4):
                widget.insert_text(' ' * 4)
                orig_line = orig_line[4:]
            if head.strip().endswith(':'):
                widget.insert_text(' ' * 4)
            self.keypress(size, 'smart home')
            self.changed = True
        elif key == 'smart home':
            widget, pos = self.get_focus()
            pos = len(widget.edit_text) - len(widget.edit_text.lstrip())
            widget.edit_pos = pos
        elif key == 'backspace':
            widget, pos = self.get_focus()
            if pos:
                text = widget.edit_text
                self.lines[pos:pos + 1] = []
                self.set_focus(pos - 1)
                widget, pos = self.get_focus()
                self.keypress(size, 'end')
                widget.edit_text += text
                self.changed = True
        elif key == 'delete':
            widget, pos = self.get_focus()
            try:
                next_widget = self.lines[pos + 1]
            except IndexError:
                pass
            else:
                widget.edit_text += next_widget.edit_text.strip()
                self.lines[pos + 1:pos + 2] = []
                self.changed = True
        elif key == 'ctrl k':
            widget, pos = self.get_focus()
            if self.last_cut_pos != pos:
                self.cut_list = []
            self.cut_list.append(widget.edit_text)
            self.last_cut_pos = pos
            self.lines[pos:pos + 1] = []
            self.changed = True
        elif key == 'ctrl u':
            widget, pos = self.get_focus()
            lines = [self._make_line_editor(t) for t in self.cut_list]
            self.lines[pos:pos] = lines
            self.changed = True
        else:
            return_value = key
        if self.changed:
            self._emit('change', self.edit_text)
            self.changed = False
            if key != 'ctrl k':
                self.last_cut_pos = None
        return return_value


class ResultColumn(urwid.WidgetWrap):
    def __init__(self, sequence_number):
        self.sequence_number = sequence_number
        self.statusbox = urwid.Text('Ready')
        self.foot = urwid.AttrMap(self.statusbox, 'status')
        self.items = urwid.SimpleListWalker([])
        self.body = urwid.ListBox(self.items)
        self.body_wrap = urwid.AttrMap(self.body, {})
        self.frame = urwid.Frame(self.body_wrap, footer=self.foot)
        urwid.WidgetWrap.__init__(self, self.frame)


class TextColumn(urwid.WidgetWrap):
    def __init__(self, text):
        self.textbox = FancyEdit(text)
        self.footer = urwid.AttrMap(urwid.Text(''), 'status')
        self.frame = urwid.Frame(self.textbox, footer=self.footer)
        urwid.WidgetWrap.__init__(self, self.frame)


class Runner(threading.Thread):
    def __init__(self, experimentor, result, text):
        self.experimentor = experimentor
        self.result = result
        self.text = text
        super().__init__()

    def print(self, *args, file=None, end='\n', sep=' '):
        if file is None or file is sys.stdout:
            self.result.items.append(urwid.Text(sep.join(str(a) for a in args)))
        else:
            print(self, *args, file=file, end=end, sep=sep)

    def run(self):
        try:
            code = compile(self.text, filename='<experimentor>', mode='exec')
            exec(code, dict(print=self.print))
        except BaseException as exc:
            with self.experimentor.lock:
                sn = self.result.sequence_number
                if self.experimentor.results[0].sequence_number <= sn:
                    while self.experimentor.results[0].sequence_number < sn:
                        self.experimentor.results.popleft()
                column = self.experimentor.columns.widget_list[1]
                column.body_wrap.set_attr_map({None: 'invalid'})
                column.statusbox.set_text(traceback.format_exc().strip())
        else:
            self.result.statusbox.set_text('')
            with self.experimentor.lock:
                sn = self.result.sequence_number
                if self.experimentor.results[0].sequence_number <= sn:
                    while self.experimentor.results[0].sequence_number < sn:
                        self.experimentor.results.popleft()
                    self.experimentor.columns.widget_list[1] = self.result
        self.experimentor.wake_up()


class Experimentor(urwid.Frame):
    palette = [
            ('normal', 'black', 'white'),
            ('status', 'white', 'dark blue'),
            ('invalid', 'dark gray', 'white'),
        ]

    def __init__(self, filename):
        self.filename = filename
        self.text = TextColumn('')
        self.reload()
        self.result = ResultColumn(0)
        self.columns = urwid.Columns([self.text, self.result], 1)
        self.col_list = self.columns.widget_list
        super().__init__(urwid.AttrMap(self.columns, 'normal'))
        self.stdout_pipe = None

        self.sequence_number = 0
        self.results = collections.deque()
        self.lock = threading.Lock()

        self.loop = urwid.MainLoop(self, self.palette)
        self.loop.screen.tty_signal_keys(
                susp='undefined',
                stop='undefined',
                start='undefined',
            )
        self.read_pipe, self.write_pipe = os.pipe()
        self.loop.watch_file(self.read_pipe, self.on_pipe)

        urwid.connect_signal(self.text.textbox, 'change', self.text_changed)

    def keypress(self, size, key):
        key = super().keypress(size, key)
        if key == 'f5':
            self.reload()
        else:
            return key

    def reload(self):
        with open(self.filename) as f:
            text = f.read()
        self.text.textbox.edit_text = text

    def main(self):
        self.start_exec(self.text.textbox.edit_text, async=False)
        self.loop.run()

    def text_changed(self, edit, text):
        self.save(text)
        self.start_exec(text)

    def start_exec(self, text, async=True):
        with self.lock:
            self.sequence_number += 1
            result = ResultColumn(self.sequence_number)
            self.results.append(result)
        runner = Runner(self, result, text)
        if async:
            runner.start()
        else:
            runner.run()

    def wake_up(self):
        os.write(self.write_pipe, b'!')

    def save(self, text):
        #self.text.footer.set_text('Saving')
        with open(self.filename, 'w') as f:
            f.write(text)
        #self.text.footer.set_text('Saved')

    def on_pipe(self):
        os.read(self.read_pipe, 1)
        with self.lock:
            self.loop.draw_screen()


Experimentor(*sys.argv[1:]).main()
