from __future__ import print_function, unicode_literals, division

import subprocess
import sys
import os
from math import pi, sin, cos, sqrt
import random

from pyglet import gl
from gillcup_graphics import Layer, GraphicsObject, Window, RealtimeClock, run

tau = 2 * pi

def run_git(*command):
    print(command)
    process = subprocess.Popen(('git',) + command, stdout=subprocess.PIPE)
    return process.stdout


visclass_by_type = {}
def visclass(cls):
    visclass_by_type[cls.type] = cls
    return cls


def circle(x, y, radius):
    iterations = int(tau * radius) * 2
    s = sin(tau / iterations)
    c = cos(tau / iterations)
    gl.glBegin(gl.GL_TRIANGLE_FAN)
    gl.glVertex2f(x, y)
    dx, dy = radius, 0
    for i in range(iterations + 1):
        gl.glVertex2f(x + dx, y + dy)
        dx, dy = (dx * c - dy * s), (dy * c + dx * s)
    gl.glEnd()


class Object(GraphicsObject):
    def __init__(self, graph, name):
        GraphicsObject.__init__(self)
        self.graph = graph
        self.name = name

        self.radius = 10
        self.pointers_in = set()
        self.drag_starts = {}

        self.vx = self.vy = 0

    def add_children(self):
        pass

    def draw(self, **kwargs):
        gl.glColor3f(*self.color)
        circle(0, 0, self.radius)
        if self.pointers_in:
            gl.glColor4f(0, 0, 1, 1)
        else:
            gl.glColor4f(0, 0, 0, 1)
        circle(0, 0, self.radius - 2)

    def hit_test(self, x, y, z):
        return x ** 2 + y ** 2 < self.radius ** 2

    def on_pointer_motion(self, pointer, x, y, z, **kwargs):
        self.pointers_in.add(pointer)
        return True

    def on_pointer_leave(self, pointer, x, y, z, **kwargs):
        self.pointers_in.remove(pointer)
        return True

    def on_pointer_press(self, pointer, x, y, z, button, **kwargs):
        self.drag_starts[pointer, button] = x, y
        return True

    def on_pointer_drag(self, pointer, x, y, z, button, **kwargs):
        start_x, start_y = self.drag_starts[pointer, button]
        self.position = self.x + x - start_x, self.y + y - start_y
        return True

    def on_pointer_release(self, pointer, x, y, z, button, **kwargs):
        del self.drag_starts[pointer, button]
        return True


@visclass
class Commit(Object):
    type = 'commit'
    color = 1, 0, 1
    def __init__(self, graph, sha):
        Object.__init__(self, graph, sha)
        self.parents = []
        self.tree = None
        stdout = run_git('cat-file', sha, '-p')
        for line in stdout:
            line = line.strip()
            name, space, value = line.partition(' ')
            if not space:
                try:
                    self.message = u''.join(stdout)
                except UnicodeDecodeError:
                    self.message = '<Unicode>'
                break
            if name == 'tree':
                self.tree = self.graph.add_object(value)
                graph.add_edge(self, self.tree, CommitTree)
            elif name == 'author':
                self.author = value
            elif name == 'committer':
                self.committer = value
            elif name == 'parent':
                parent = self.graph.add_object(value)
                self.parents.append(parent)
                graph.add_edge(self, parent, CommitParent)
            else:
                print('Warning: unknown commit line:', line)

    def add_children(self):
        for parent in self.parents:
            self.graph.add_object(parent.name)
        if self.graph.show_trees and self.tree:
            self.graph.add_object(self.tree.name)

    @property
    def summary(self):
        return self.message.partition('\n')[0]

@visclass
class Tree(Object):
    type = 'tree'
    color = 0, 1, 0
    summary = None
    def __init__(self, graph, sha):
        Object.__init__(self, graph, sha)
        self.children = {}
        for line in run_git('cat-file', sha, '-p'):
            line = line.strip()
            info, tab, filename = line.partition('\t')
            obj = self.add_child(info, filename)
            self.children[filename] = obj
            graph.add_edge(self, obj, TreeEntry, filename)

    def add_children(self):
        for child in self.children.values():
            self.graph.add_object(child.name)

    def add_child(self, info, name):
        mode, type, sha = info.split(' ')
        child = self.graph.add_object(sha)
        self.children[name] = child
        return child


@visclass
class Blob(Object):
    type = 'blob'
    summary = None
    color = 0, 1, 1
    def __init__(self, graph, sha):
        Object.__init__(self, graph, sha)
        self.contents = run_git('cat-file', sha, '-p').read()


class Ref(Object):
    type = 'ref'
    color = 1, 1, 0
    def __init__(self, graph, name, target):
        Object.__init__(self, graph, name)
        self.target = target
        graph.add_edge(self, target, RefTarget)

    @property
    def summary(self):
        return self.target.name


class Edge(GraphicsObject):
    def __init__(self, graph, a, b):
        GraphicsObject.__init__(self)
        self.graph = graph
        self.a = a
        self.b = b

    @property
    def summary(self):
        return self.type

    def draw(self, **kwargs):
        dx = self.a.x - self.b.x
        dy = self.a.y - self.b.y
        dist = sqrt(dx ** 2 + dy ** 2)
        if dist == 0:
            return
        width = self.a.radius * self.b.radius / 100
        cx = dy / dist * width
        cy = dx / dist * width
        gl.glBegin(gl.GL_TRIANGLE_STRIP)
        gl.glColor3f(*self.a.color)
        gl.glVertex2f(self.a.x + cx, self.a.y - cy)
        gl.glColor3f(*self.b.color)
        gl.glVertex2f(self.b.x + cx, self.b.y - cy)
        gl.glColor3f(*self.a.color)
        gl.glVertex2f(self.a.x - cx, self.a.y + cy)
        gl.glColor3f(*self.b.color)
        gl.glVertex2f(self.b.x - cx, self.b.y + cy)
        gl.glEnd()

    def hit_test(self, *args):
        return False

    def force(self, distance, ndx, ndy, dx, dy):
        return -ndx * 1e2, -ndy * 1e2


class CommitTree(Edge):
    type = 'tree'
    color = 0, 1, 0

    def force(self, distance, ndx, ndy, dx, dy):
        return (
            -ndx * (10 + distance ** 2 / 100),
            -ndy * (10 + distance ** 2 / 100) + distance)


class CommitParent(Edge):
    type = 'parent'
    color = 1, 0, 1

    def force(self, distance, ndx, ndy, dx, dy):
        return (
            -ndx * (10 + distance ** 2 / 1000),
            -ndy * (10 + distance ** 2 / 1000) + 100)


class RefTarget(Edge):
    type = 'target'
    color = 1, 1, 0

    def force(self, distance, ndx, ndy, dx, dy):
        return (
            -ndx * (10 + distance ** 2 / 100) + 10,
            -ndy * (10 + distance ** 2 / 100) + 10)


class TreeEntry(Edge):
    type = 'entry'
    color = 0, 1, 0
    def __init__(self, graph, a, b, filename):
        Edge.__init__(self, graph, a, b)
        self.filename = filename

    @property
    def summary(self):
        return './' + self.filename

    def force(self, distance, ndx, ndy, dx, dy):
        return (
            -ndx * (10 + distance ** 2 / 1000),
            -ndy * (10 + distance ** 2 / 1000) + 20)


class Graph(Layer):
    def __init__(self,  clock):
        Layer.__init__(self)

        self.show_trees = True

        self.lingering = {}
        self.objects = {}
        self.edges = {}
        self.update()
        self.update()

        self.clock = clock
        self.time = clock.time
        self.simulate = self.simulate
        clock.schedule_update_function(self.simulate)

    def update(self):
        try:
            del self._children
        except AttributeError:
            pass
        self.lingering.update(self.objects)
        self.objects = {}
        for line in run_git('ls-files', '--stage'):
            info = line.strip().split(' ')
            obj = self.add_object(info[1])
        for line in run_git('show-ref'):
            sha, name = line.strip().split()
            obj = self.add_object(sha)
            self.add_ref(name, obj)
        for line in run_git('symbolic-ref', 'HEAD'):
            name = line.strip()
            self.add_ref('HEAD', self.add_ref(name))

    def _add(func):
        def adder(self, name, *args, **kwargs):
            try:
                obj = self.objects[name]
            except KeyError:
                try:
                    obj = self.lingering[name]
                except KeyError:
                    obj = func(self, name, *args, **kwargs)
                else:
                    del self.lingering[name]
                    obj.add_children()
            self.objects[name] = obj
            return obj
        return adder

    @_add
    def add_ref(self, name, target=None):
        if target is None:
            for line in run_git('rev-parse', name):
                target = self.add_object(line.strip())
        assert target is not None
        return Ref(self, name, target)

    @_add
    def add_object(self, sha):
        obj_type = run_git('cat-file', sha, '-t').read().strip()
        try:
            visclass = visclass_by_type[obj_type]
        except KeyError:
            print('Warning: unknown object type:', obj_type)
            return
        return visclass(self, sha)

    def add_edge(self, a, b, cls, *args):
        try:
            edge = self.edges[a, b][cls, args]
        except KeyError:
            edge = cls(self, a, b, *args)
            self.edges.setdefault((a, b), {})[cls, args] = edge
        else:
            assert isinstance(edge, cls)
        return edge

    def dump(self):
        for name, obj in self.objects.items():
            print(obj.name, obj.type, obj.summary or '')
            for (a, b), dct in self.edges.items():
                for junk, edge in dct.items():
                    if a is obj:
                        print(' --', edge.summary, '->', b.name)
                    if b is obj:
                        print(' <-', edge.summary, '--', a.name)

    @property
    def children(self):
        try:
            return self._children
        except AttributeError:
            self._children = []
            for (a, b), v in self.edges.items():
                if a.name in self.objects and b.name in self.objects:
                    self._children += v.values()
            self._children += self.objects.values()
        return self._children

    @children.setter
    def children(self, v):
        pass

    def simulate(self):
        dt = self.clock.time - self.time
        dt *= 2
        self.time = self.clock.time
        cx = cy = 0
        objects = self.objects.values()
        for obj in objects:
            fx = fy = 0
            for obj2 in self.objects.values():
                if obj is obj2:
                    continue
                dx = obj.x - obj2.x
                dy = obj.y - obj2.y
                distance = sqrt(dx ** 2 + dy ** 2)
                if not distance:
                    rx = random.random() - 0.5
                    ry = random.random() - 0.5
                    obj.x += rx * obj.radius * 5
                    obj.y += ry * obj.radius * 5
                    continue
                ndx = dx / distance
                ndy = dy / distance
                if distance < obj.radius + obj2.radius:
                    fx += obj.radius * ndx * 1e2
                    fy += obj.radius * ndy * 1e2
                else:
                    # Repulsion
                    repulsion = 1e7 / distance ** 3
                    fx += ndx * repulsion
                    fy += ndy * repulsion
                for edge in self.edges.get((obj, obj2), {}).values():
                    dfx, dfy = edge.force(distance, ndx, ndy, dx, dy)
                    fx += dfx
                    fy += dfy
                for edge in self.edges.get((obj2, obj), {}).values():
                    dfx, dfy = edge.force(distance, -ndx, -ndy, -dx, -dy)
                    fx -= dfx
                    fy -= dfy
            # Gravity
            fx -= obj.x / 100
            fy -= obj.y / 100
            # Force
            obj.vx += fx * dt
            obj.vy += fy * dt
            # Resistance
            obj.vx *= 0.9
            obj.vy *= 0.9
            # Center calculation
            cx += obj.x
            cy += obj.y
        cx /= len(objects)
        cy /= len(objects)
        for obj in objects:
            if not obj.pointers_in:
                obj.position = (
                    obj.x + obj.vx * dt - cx * dt,
                    obj.y + obj.vy * dt - cy * dt)

    def on_text(self, keyboard, text):
        if 't' in text.lower():
            self.show_trees = not self.show_trees
            self.update()
            print(self.show_trees)
        if '+' in text.lower():
            self.scale = self.scale_x + 0.1
        if '-' in text.lower():
            self.scale = self.scale_x - 0.1

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
            self.scale = self.scale_x + scroll_x


class GVWindow(Window):
    def on_resize(self, width, height):
        super(Window, self).on_resize(width, height)
        layer = self.layer
        layer.position = width / 2, height / 2


def main():
    clock = RealtimeClock()
    g = Graph(clock)
    g.dump()

    GVWindow(g, width=400, height=400, resizable=True)
    run()


if __name__ == '__main__':
    os.chdir(sys.argv[1])
    main()
