# Blender plugin for generating celtic knot curves from 3d meshes
# See README for more information
#
# The MIT License (MIT)
#
# Copyright (c) 2013 Adam Newgas
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

bl_info = {
    "name": "Celtic Knot",
    "description": "",
    "author": "Adam Newgas",
    "version": (0,1,2),
    "blender": (2, 68, 0),
    "location": "View3D > Add > Curve",
    "warning": "",
    "wiki_url": "https://github.com/BorisTheBrave/celtic-knot/wiki",
    "category": "Add Curve"}

import bpy
import bmesh
from bpy_extras import object_utils
from collections import defaultdict
from mathutils import Vector
from math import pi, sin, cos
from random import random, seed, choice, randrange

HANDLE_TYPE_MAP = {"AUTO": "AUTOMATIC", "ALIGNED": "ALIGNED"}

# Twist types
TWIST_CW = "TWIST_CW"
STRAIGHT = "STRAIGHT"
TWIST_CCW = "TWIST_CCW"
IGNORE = "IGNORE"

# output types
BEZIER = "BEZIER"
PIPE = "PIPE"
RIBBON = "RIBBON"


def get_celtic_twists(bm):
    seed(0)
    twists = []
    for edge in bm.edges:
        if len(edge.link_loops) == 0:
            twists.append(IGNORE)
        else:
            if random() < 0.5:
                twists.append(TWIST_CW)
            else:
                twists.append(STRAIGHT)
    return twists


def get_twill_twists(bm):
    # Largely based off "Cyclic Twill-Woven Objects", Akleman, Chen, Chen, Xing, Gross (2011)
    seed(0)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    def move(loop, forward):
        """Advances the loop one along the braid in the direction indicated,
        also returning the new loop-local direction consistent with the passed in one."""
        if forward:
            # Follow the face around, ignoring boundary edges
            loop = loop.link_loop_next
            v = loop.vert.index
            # Find next radial loop
            assert loop.link_loops[0] != loop
            loop = loop.link_loops[0]
            forward = loop.vert.index == v
            return loop, forward
        else:
            # Follow the face around, ignoring boundary edges
            v = loop.vert.index
            loop = loop.link_loop_prev
            # Find next radial loop
            assert loop.link_loops[-1] != loop
            loop = loop.link_loops[-1]
            forward = loop.vert.index == v
            return loop, forward

    def swap(loop, forward):
        """Switch from a loop to its partner on the same edge,
        also returning the new loop-local direction consistent with the passed in one."""
        v = loop.vert.index
        assert len(loop.link_loops) == 1, "Found link loop of size {}, only manifold meshes supported currently".format(len(loop.link_loops))
        loop = loop.link_loops[0]
        forward = (loop.vert.index == v) == forward
        return loop, forward

    class Votes:
        def __init__(self, cw=0, ccw=0):
            self.cw = cw
            self.ccw = ccw

        def __add__(self, other):
            return Votes(self.cw + other.cw, self.ccw + other.ccw)

    def edge_cond_vote(loop, forward):
        next, next_forward = move(loop, forward)
        next2, _ = move(next, next_forward)
        twist1 = coloring[next.edge.index]
        twist2 = coloring[next2.edge.index]
        if twist1 is None or twist2 is None:
            return Votes()
        if twist1 is TWIST_CW and twist2 is TWIST_CW:
            return Votes(0, 1)
        if twist1 is TWIST_CCW and twist2 is TWIST_CCW:
            return Votes(1, 0)
        return Votes(1, 1)

    def face_cond_vote(loop, forward):
        s, s_forward = move(loop, forward)
        p, _ = move(*swap(loop, not forward))
        f, _ = move(*swap(s, s_forward))
        twist_s = coloring[s.edge.index]
        twist_p = coloring[p.edge.index]
        twist_f = coloring[f.edge.index]
        if twist_s is None or twist_p is None or twist_f is None:
            return Votes()
        if twist_p != twist_f:
            if twist_s is TWIST_CW:
                return Votes(1, 0)
            else:
                return Votes(0, 1)
        return Votes(1, 1)

    def vert_cond_vote(loop, forward):
        s, s_forward = move(loop, forward)
        p, _ = move(*swap(loop, forward))
        f, _ = move(*swap(s, not s_forward))
        twist_s = coloring[s.edge.index]
        twist_p = coloring[p.edge.index]
        twist_f = coloring[f.edge.index]
        if twist_s is None or twist_p is None or twist_f is None:
            return Votes()
        if twist_p != twist_f:
            if twist_s is TWIST_CW:
                return Votes(1, 0)
            else:
                return Votes(0, 1)
        return Votes(1, 1)

    def count_votes(edge):
        votes = Votes()
        assert len(edge.link_loops) == 2
        loop1 = edge.link_loops[0]
        loop2 = edge.link_loops[1]
        # Edge condition votes
        votes += edge_cond_vote(loop1, True)
        votes += edge_cond_vote(loop1, False)
        votes += edge_cond_vote(loop2, True)
        votes += edge_cond_vote(loop2, False)
        # Face condition votes
        votes += face_cond_vote(loop1, True)
        votes += face_cond_vote(loop1, False)
        votes += face_cond_vote(loop2, True)
        votes += face_cond_vote(loop2, False)
        # Vert condition votes
        votes += vert_cond_vote(loop1, True)
        votes += vert_cond_vote(loop1, False)
        votes += vert_cond_vote(loop2, True)
        votes += vert_cond_vote(loop2, False)

        return votes

    # Initialize
    frontier = set()
    coloring = [None] * len(bm.edges)

    def color_edge(edge, twist):
        if edge.index in frontier:
            frontier.remove(edge.index)
        coloring[edge.index] = twist
        for v in edge.verts:
            for other in v.link_edges:
                if coloring[other.index] is None:
                    frontier.add(other.index)

    v0 = randrange(len(bm.verts))
    for e in bm.verts[v0].link_edges:
        color_edge(e, TWIST_CW)

    # Color the best choice of edge
    while frontier:
        votes = {e: count_votes(bm.edges[e]) for e in frontier}
        m = max(max(v.cw, v.ccw) for v in votes.values())
        best_edge, best_votes = choice([(k, v) for (k, v) in votes.items() if v.cw == m or v.ccw == m])
        set_twist = TWIST_CW if best_votes.cw > best_votes.ccw else TWIST_CCW
        color_edge(bm.edges[best_edge], set_twist)

    return coloring


def get_offset(weave_up, weave_down, twist, forward):
    if twist is TWIST_CW:
        return weave_up if forward else weave_down
    elif twist is TWIST_CCW:
        return weave_down if forward else weave_up
    elif twist is STRAIGHT:
        return (weave_down + weave_up) / 2.0


def lerp(v1, v2, t):
    return v1 * (1 - t) + v2 * t


class RibbonBuilder:
    def __init__(self, weave_up, weave_down, length, breadth):
        self.weave_up = weave_up
        self.weave_down = weave_down
        self.vertices = []
        self.faces = []
        self.prev_out_verts = None
        self.first_in_verts = None
        self.c = length
        self.w = breadth

    def get_sub_face(self, v1, v2, v3, v4):
        hc = self.c / 2.0
        hw = self.w / 2.0
        return (
            lerp(lerp(v1, v4, 0.5 - hc), lerp(v2, v3, 0.5 - hc), 0.5 - hw),
            lerp(lerp(v1, v4, 0.5 - hc), lerp(v2, v3, 0.5 - hc), 0.5 + hw),
            lerp(lerp(v1, v4, 0.5 + hc), lerp(v2, v3, 0.5 + hc), 0.5 + hw),
            lerp(lerp(v1, v4, 0.5 + hc), lerp(v2, v3, 0.5 + hc), 0.5 - hw),
        )

    def start_strand(self):
        self.first_in_verts = None
        self.prev_out_verts = None

    def add_loop(self, prev_loop, loop, twist, forward):
        normal = loop.calc_normal() + prev_loop.calc_normal()
        normal.normalize()
        offset = get_offset(self.weave_up, self.weave_down, twist, forward) * normal

        center1 = prev_loop.face.calc_center_median()
        center2 = loop.face.calc_center_median()
        v1 = loop.vert.co
        v2 = loop.link_loop_next.vert.co

        if twist is STRAIGHT:
            if forward:
                v1, center1, v2, center2 = center1, v1, v2, center1
            else:
                v1, center1, v2, center2 = v2, center1, center1, v1
        else:
            if not forward:
                v1, center1, v2, center2 = center1, v2, center2, v1

        v1, center1, v2, center2 = self.get_sub_face(v1, center1, v2, center2)

        i = len(self.vertices)
        self.vertices.append(v1 + offset)
        self.vertices.append(center1 + offset)
        self.vertices.append(v2 + offset)
        self.vertices.append(center2 + offset)
        # self.faces.append([i, i+1, i+2, i+3])
        self.faces.append([i, i + 1, i + 2])
        self.faces.append([i, i + 2, i + 3])
        in_verts = [i + 1, i + 0]
        out_verts = [i + 3, i + 2]

        if self.first_in_verts is None:
            self.first_in_verts = in_verts
        if self.prev_out_verts is not None:
            self.faces.append(self.prev_out_verts + in_verts)
        self.prev_out_verts = out_verts

    def end_strand(self):
        self.faces.append(self.prev_out_verts + self.first_in_verts)

    def make_mesh(self):
        me = bpy.data.meshes.new("")
        me.from_pydata(self.vertices, [], self.faces)
        me.update(calc_edges=True)
        return me


class BezierBuilder:
    def __init__(self, bm, crossing_angle, crossing_strength, handle_type, weave_up, weave_down):
        # Cache some values
        self.s = sin(crossing_angle) * crossing_strength
        self.c = cos(crossing_angle) * crossing_strength
        self.handle_type = handle_type
        self.weave_up = weave_up
        self.weave_down = weave_down
        # Create the new object
        self.curve = bpy.data.curves.new("Celtic", "CURVE")
        self.curve.dimensions = "3D"
        self.curve.twist_mode = "MINIMUM"
        # Compute all the midpoints of each edge
        self.midpoints = []
        for e in bm.edges:
            v1 = e.verts[0]
            v2 = e.verts[1]
            m = (v1.co + v2.co) / 2.0
            self.midpoints.append(m)
        # Per strand stuff
        self.current_spline = None
        self.cos = None
        self.handle_lefts = None
        self.handle_rights = None
        self.first = True

    def start_strand(self):
        self.current_spline = self.curve.splines.new("BEZIER")
        self.current_spline.use_cyclic_u = True
        # Data for the strand
        # It's faster to store in an array and load into blender
        # at once
        self.cos = []
        self.handle_lefts = []
        self.handle_rights = []
        self.first = True

    def add_loop(self, prev_loop, loop, twist, forward):
        if not self.first:
            self.current_spline.bezier_points.add()
        self.first = False
        midpoint = self.midpoints[loop.edge.index]
        normal = loop.calc_normal() + prev_loop.calc_normal()
        normal.normalize()
        offset = get_offset(self.weave_up, self.weave_down, twist, forward) * normal
        midpoint = midpoint + offset
        self.cos.extend(midpoint)
        if self.handle_type != "AUTO":
            tangent = loop.link_loop_next.vert.co - loop.vert.co
            tangent.normalize()
            binormal = normal.cross(tangent).normalized()
            if not forward: tangent *= -1
            s_binormal = self.s * binormal
            c_tangent = self.c * tangent
            handle_left = midpoint - s_binormal - c_tangent
            handle_right = midpoint + s_binormal + c_tangent
            self.handle_lefts.extend(handle_left)
            self.handle_rights.extend(handle_right)

    def end_strand(self):
        points = self.current_spline.bezier_points
        points.foreach_set("co", self.cos)
        if self.handle_type != "AUTO":
            points.foreach_set("handle_left", self.handle_lefts)
            points.foreach_set("handle_right", self.handle_rights)


def visit_strands(bm, twists, builder):
    # Stores which loops the curve has already passed through
    loops_entered = defaultdict(lambda: False)
    loops_exited = defaultdict(lambda: False)

    # Loops on the boundary of a surface
    def ignorable_loop(loop):
        return len(loop.link_loops) == 0

    # Starting at loop, build a curve one vertex at a time
    # until we start where we came from
    # Forward means that for any two edges the loop crosses
    # sharing a face, it is passing through in clockwise order
    # else anticlockwise
    def make_loop(loop, forward):
        builder.start_strand()
        while True:
            if forward:
                if loops_exited[loop]: break
                loops_exited[loop] = True
                # Follow the face around, ignoring boundary edges
                while True:
                    loop = loop.link_loop_next
                    if not ignorable_loop(loop): break
                assert loops_entered[loop] == False
                loops_entered[loop] = True
                v = loop.vert.index
                prev_loop = loop
                # Find next radial loop
                twist = twists[loop.edge.index]
                if twist in (TWIST_CCW, TWIST_CW):
                    assert loop.link_loops[0] != loop
                    loop = loop.link_loops[0]
                forward = loop.vert.index == v
            else:
                if loops_entered[loop]: break
                loops_entered[loop] = True
                # Follow the face around, ignoring boundary edges
                while True:
                    v = loop.vert.index
                    loop = loop.link_loop_prev
                    if not ignorable_loop(loop): break
                assert loops_exited[loop] == False
                loops_exited[loop] = True
                prev_loop = loop
                # Find next radial loop
                twist = twists[loop.edge.index]
                if twist in (TWIST_CCW, TWIST_CW):
                    assert loop.link_loops[-1] != loop
                    loop = loop.link_loops[-1]
                forward = loop.vert.index == v
            builder.add_loop(prev_loop, loop, twist, forward)
        builder.end_strand()

    # Attempt to start a loop at each untouched loop in the entire mesh
    for face in bm.faces:
        for loop in face.loops:
            if ignorable_loop(loop): continue
            if not loops_exited[loop]: make_loop(loop, True)
            if not loops_entered[loop]: make_loop(loop, False)


def create_bezier(context, bm, twists,
                  crossing_angle, crossing_strength, handle_type, weave_up, weave_down):
    builder = BezierBuilder(bm, crossing_angle, crossing_strength, handle_type, weave_up, weave_down)
    visit_strands(bm, twists, builder)
    curve = builder.curve

    orig_obj = context.active_object
    # Create an object from the curve
    object_utils.object_data_add(context, curve, operator=None)
    # Set the handle type (this is faster than setting it pointwise)
    bpy.ops.object.editmode_toggle()
    bpy.ops.curve.select_all(action="SELECT")
    bpy.ops.curve.handle_type_set(type=HANDLE_TYPE_MAP[handle_type])
    # Some blender versions lack the default
    bpy.ops.curve.radius_set(radius=1.0)
    bpy.ops.object.editmode_toggle()
    # Restore active selection
    curve_obj = context.active_object
    context.scene.objects.active = orig_obj
    return curve_obj


def create_ribbon(context, bm, twists, weave_up, weave_down, length, breadth):
    builder = RibbonBuilder(weave_up, weave_down, length, breadth)
    visit_strands(bm, twists, builder)
    mesh = builder.make_mesh()
    orig_obj = context.active_object
    object_utils.object_data_add(context, mesh, operator=None)
    mesh_obj = context.active_object
    context.scene.objects.active = orig_obj
    return mesh_obj


def create_pipe_from_bezier(context, curve_obj, thickness):
    bpy.ops.curve.primitive_bezier_circle_add()
    bpy.ops.transform.resize(value=(thickness,) * 3)
    circle = context.active_object
    curve_obj.data.bevel_object = circle
    curve_obj.select = True
    context.scene.objects.active = curve_obj
    # For some reason only works with keep_original=True
    bpy.ops.object.convert(target="MESH", keep_original=True)
    new_obj = context.scene.objects.active
    new_obj.select = False
    curve_obj.select = True
    circle.select = True
    bpy.ops.object.delete()
    new_obj.select = True
    context.scene.objects.active = new_obj


class CelticKnotOperator(bpy.types.Operator):
    bl_idname = "object.celtic_knot_operator"
    bl_label = "Celtic Knot"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}

    weave_types = [("CELTIC","Celtic","All crossings use same orientation"),
                   ("TWILL","Twill","Over two then under two")]
    weave_type = bpy.props.EnumProperty(items=weave_types,
                                         name="Weave Type",
                                         description="Determines which crossings are over or under",
                                         default="CELTIC")

    weave_up = bpy.props.FloatProperty(name="Weave Up",
                                       description="Distance to shift curve upwards over knots",
                                       subtype="DISTANCE",
                                       unit="LENGTH")
    weave_down = bpy.props.FloatProperty(name="Weave Down",
                                         description="Distance to shift curve downward under knots",
                                         subtype="DISTANCE",
                                         unit="LENGTH")
    output_types = [(BEZIER, "Bezier", "Bezier curve"),
                    (PIPE, "Pipe", "Rounded solid mesh"),
                    (RIBBON, "Ribbon", "Flat plane mesh")]
    output_type = bpy.props.EnumProperty(items=output_types,
                                         name="Output Type",
                                         description="Controls what type of curve/mesh is generated",
                                         default=BEZIER)

    handle_types = [("ALIGNED","Aligned","Points at a fixed crossing angle"),
                    ("AUTO","Auto","Automatic control points")]
    handle_type = bpy.props.EnumProperty(items=handle_types,
                                         name="Handle Type",
                                         description="Controls what type the bezier control points use",
                                         default="AUTO")
    crossing_angle = bpy.props.FloatProperty(name="Crossing Angle",
                                             description="Aligned only: the angle between curves in a knot",
                                             default=pi/4,
                                             min=0,max=pi/2,
                                             subtype="ANGLE",
                                             unit="ROTATION")
    crossing_strength = bpy.props.FloatProperty(name="Crossing Strength",
                                                description="Aligned only: strenth of bezier control points",
                                                soft_min=0,
                                                subtype="DISTANCE",
                                                unit="LENGTH")
    thickness = bpy.props.FloatProperty(name="Thickness",
                                        description="Radius of tube around curve (zero disables)",
                                        soft_min=0,
                                        subtype="DISTANCE",
                                        unit="LENGTH")
    length = bpy.props.FloatProperty(name="Length",
                                     description="Percent along faces that the ribbon runs parallel",
                                     subtype="PERCENTAGE",
                                     unit="NONE",
                                     default=0.9,
                                     soft_min=0.0,
                                     soft_max=1.0)
    breadth = bpy.props.FloatProperty(name="Breadth",
                                      description="Ribbon width as a percentage across faces.",
                                      subtype="PERCENTAGE",
                                      unit="NONE",
                                      default=0.5,
                                      soft_min=0.0,
                                      soft_max=1.0)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "weave_type")
        layout.prop(self, "weave_up")
        layout.prop(self, "weave_down")
        layout.prop(self, "output_type")
        if self.output_type in (BEZIER, PIPE):
            layout.prop(self, "handle_type")
            if self.handle_type != "AUTO":
                layout.prop(self, "crossing_angle")
                layout.prop(self, "crossing_strength")
        elif self.output_type == RIBBON:
            layout.prop(self, "length")
            layout.prop(self, "breadth")
        if self.output_type == PIPE:
            layout.prop(self, "thickness")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        #return True
        return ((ob is not None) and
                (ob.mode == "OBJECT") and
                (ob.type == "MESH") and
                (context.mode == "OBJECT"))

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        if self.weave_type == "CELTIC":
            twists = get_celtic_twists(bm)
        else:
            twists = get_twill_twists(bm)

        if self.output_type in (BEZIER, PIPE):
            curve_obj = create_bezier(context, bm, twists,
                          self.crossing_angle,
                          self.crossing_strength,
                          self.handle_type,
                          self.weave_up,
                          self.weave_down)

            # If thick, then give it a bevel_object and convert to mesh
            if self.output_type == PIPE and self.thickness > 0:
                create_pipe_from_bezier(context, curve_obj, self.thickness)
        else:
            create_ribbon(context, bm, twists, self.weave_up, self.weave_down, self.length, self.breadth)
        return {'FINISHED'}

def menu_func(self, context):
    self.layout.operator(CelticKnotOperator.bl_idname,
                         text="Celtic Knot From Mesh",
                         icon='PLUGIN')

def register():
    bpy.utils.register_module(__name__)
    bpy.types.INFO_MT_curve_add.append(menu_func)


def unregister():
    bpy.types.INFO_MT_curve_add.remove(menu_func)
    bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
    register()
