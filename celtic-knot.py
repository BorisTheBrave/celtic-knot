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

## General math utilites

def is_boundary(loop):
    """Is a given loop on the boundary of a manifold (only connected to one face)"""
    return len(loop.link_loops) == 0


def lerp(v1, v2, t):
    return v1 * (1 - t) + v2 * t

def cyclic_zip(l):
    i = iter(l)
    first = prev = next(i)
    for item in i:
        yield prev, item
        prev = item
    yield prev, first


def edge_midpoint(edge):
    v1 = edge.verts[0]
    v2 = edge.verts[1]
    return (v1.co + v2.co) / 2.0


def bmesh_from_pydata(vertices, faces):
    bm = bmesh.new()
    for v in vertices:
        bm.verts.new(v)
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    for f in faces:
        bm.faces.new([bm.verts[v] for v in f])
    bm.edges.index_update()
    bm.edges.ensure_lookup_table()
    i = 0
    for edge in bm.edges:
        for loop in edge.link_loops:
            loop.index = i
            i += 1
    return bm


## Remeshing operations (replacing one bmesh with another)

def remesh_midedge_subdivision(bm):
    edge_index_to_new_index = {}
    vert_index_to_new_index = {}
    new_vert_count = 0
    new_verts = []
    new_faces = []
    for vert in bm.verts:
        vert_index_to_new_index[vert.index] = new_vert_count
        new_verts.append(vert.co)
        new_vert_count += 1
    for edge in bm.edges:
        edge_index_to_new_index[edge.index] = new_vert_count
        new_verts.append(edge_midpoint(edge))
        new_vert_count += 1
    # Add a face per face in the original mesh, with twice as many vertices
    for face in bm.faces:
        new_face = []
        for loop in face.loops:
            new_face.append(vert_index_to_new_index[loop.vert.index])
            new_face.append(edge_index_to_new_index[loop.edge.index])
        new_faces.append(new_face)
    return bmesh_from_pydata(new_verts, new_faces)


def remesh_medial(bm):
    edge_index_to_new_index = {}
    vert_index_to_new_index = {}
    new_vert_count = 0
    new_verts = []
    new_faces = []
    for vert in bm.verts:
        vert_index_to_new_index[vert.index] = new_vert_count
        new_verts.append(vert.co)
        new_vert_count += 1
    for edge in bm.edges:
        edge_index_to_new_index[edge.index] = new_vert_count
        new_verts.append(edge_midpoint(edge))
        new_vert_count += 1
    # Add a face for each face in the original mesh
    for face in bm.faces:
        new_face = []
        for loop in face.loops:
            new_face.append(edge_index_to_new_index[loop.edge.index])
        new_faces.append(new_face)
    # Add a fan for each vert in the original mesh
    for vert in bm.verts:
        if len(vert.link_loops) <= 1:
            continue
        v0 = vert_index_to_new_index[vert.index]
        loop0 = vert.link_loops[0]
        vert_edges = []
        first = d = DirectedLoop(loop0, loop0.vert.index != vert.index)
        while True:
            vert_edges.append(d.loop.edge)
            d = d.next_face_loop.next_edge_loop.reversed
            if d.loop == first.loop:
                break
        for edge1, edge2 in cyclic_zip(vert_edges):
            v1 = edge_index_to_new_index[edge1.index]
            v2 = edge_index_to_new_index[edge2.index]
            new_faces.append([v0, v1, v2])
    return bmesh_from_pydata(new_verts, new_faces)


REMESH_TYPES = [("NONE", "None", ""),
                ("EDGE_SUBDIVIDE", "Edge Subdivide", "Subdivide every edge"),
                ("MEDIAL", "Medial", "Replace every vertex with a fan of faces")]


def remesh(bm, remesh_type):
    if remesh_type is None or remesh_type == "NONE":
        return bm
    if remesh_type == "EDGE_SUBDIVIDE":
        return remesh_midedge_subdivision(bm)
    if remesh_type == "MEDIAL":
        return remesh_medial(bm)


class DirectedLoop:
    """Stores an edge loop and a particular facing along it."""
    def __init__(self, loop, forward):
        self.loop = loop
        self.forward = forward


    @property
    def reversed(self):
        return DirectedLoop(self.loop, not self.forward)

    @property
    def next_face_loop(self):
        loop = self.loop
        forward = self.forward
        # Follow the face around, ignoring boundary edges
        while True:
            if forward:
                loop = loop.link_loop_next
            else:
                loop = loop.link_loop_prev
            if not is_boundary(loop):
                break
        return DirectedLoop(loop, forward)

    @property
    def next_edge_loop(self):
        loop = self.loop
        forward = self.forward
        if forward:
            v = loop.vert.index
            loop = loop.link_loops[0]
            forward = (loop.vert.index == v) == forward
            return DirectedLoop(loop, forward)
        else:
            v = loop.vert.index
            loop = loop.link_loops[-1]
            forward = (loop.vert.index == v) == forward
            return DirectedLoop(loop, forward)


def get_celtic_twists(bm, twist_prob):
    """Gets a twist per edge for celtic knot style patterns.
    These are also called "plain weavings"."""
    seed(0)
    twists = []
    for edge in bm.edges:
        if len(edge.link_loops) == 0:
            twists.append(IGNORE)
        else:
            if random() < twist_prob:
                twists.append(TWIST_CW)
            else:
                twists.append(STRAIGHT)
    return twists


def strand_part(prev_loop, loop, forward):
    """A strand part uniquely identifies one point on a strande
    crossing a particular edge."""
    return forward, frozenset((prev_loop.index, loop.index))


class StrandAnalysisBuilder:
    """Computes information about which strand parts belong to which strands."""
    def __init__(self):
        self.crossings = defaultdict(list)
        self.current_strand_index = 0
        self.strand_indices = {}
        self.strand_size = defaultdict(int)

    # Builder methods
    def start_strand(self):
        pass

    def add_loop(self, prev_loop, loop, twist, forward):
        if twist != STRAIGHT:
            self.crossings[loop.edge.index].append(self.current_strand_index)
        self.strand_indices[strand_part(prev_loop, loop, forward)] = self.current_strand_index
        self.strand_size[self.current_strand_index] += 1

    def end_strand(self):
        self.current_strand_index += 1

    def all_crossings(self):
        return set(frozenset([x, y]) for l in self.crossings.values() for x in l for y in l if x != y)

    def get_strands(self):
        """Returns a dict of strand parts to integers"""
        return self.strand_indices

    def get_strand_sizes(self):
        return self.strand_size

    def get_braids(self):
        """Partitions the strands so any two crossing strands are in separate partitions.
        Each partition is called a braid.
        Returns a dict of strand parts to integers"""
        crossings = self.all_crossings()
        braids = defaultdict(list)
        braid_count = 0
        for s in range(self.current_strand_index):
            crossed_braids = set(braids[t] for p in crossings if s in p for t in p if t in braids)
            for b in range(braid_count):
                if b not in crossed_braids:
                    break
            else:
                b = braid_count
                braid_count += 1
            braids[s] = b
        return {k: braids[v] for (k, v) in self.strand_indices.items()}


def get_twill_twists(bm):
    """Gets twists per edge that describe a pattern where each strand goes over 2 then under 2,
    and adjacent strands have the pattern offset by one.
    This is heuristic, it's not always possible for some meshes.
    Largely based off "Cyclic Twill-Woven Objects", Akleman, Chen, Chen, Xing, Gross (2011)
    """
    seed(0)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    def move(d):
        return d.next_face_loop.next_edge_loop

    def swap(d):
        return d.next_edge_loop

    class Votes:
        def __init__(self, cw=0, ccw=0):
            self.cw = cw
            self.ccw = ccw

        def __add__(self, other):
            return Votes(self.cw + other.cw, self.ccw + other.ccw)

    def edge_cond_vote(dloop):
        next = move(dloop)
        next2 = move(next)
        twist1 = coloring[next.loop.edge.index]
        twist2 = coloring[next2.loop.edge.index]
        if twist1 is None or twist2 is None:
            return Votes()
        if twist1 is TWIST_CW and twist2 is TWIST_CW:
            return Votes(0, 1)
        if twist1 is TWIST_CCW and twist2 is TWIST_CCW:
            return Votes(1, 0)
        return Votes(1, 1)

    def face_cond_vote(dloop):
        s = move(dloop)
        p = move(swap(dloop.reversed))
        f = move(swap(s))
        twist_s = coloring[s.loop.edge.index]
        twist_p = coloring[p.loop.edge.index]
        twist_f = coloring[f.loop.edge.index]
        if twist_s is None or twist_p is None or twist_f is None:
            return Votes()
        if twist_p != twist_f:
            if twist_s is TWIST_CW:
                return Votes(1, 0)
            else:
                return Votes(0, 1)
        return Votes(1, 1)

    def vert_cond_vote(dloop):
        s = move(dloop)
        p = move(swap(dloop))
        f = move(swap(s.reversed))
        twist_s = coloring[s.loop.edge.index]
        twist_p = coloring[p.loop.edge.index]
        twist_f = coloring[f.loop.edge.index]
        if twist_s is None or twist_p is None or twist_f is None:
            return Votes()
        if twist_p != twist_f:
            if twist_s is TWIST_CW:
                return Votes(1, 0)
            else:
                return Votes(0, 1)
        return Votes(1, 1)

    def count_votes(edge_index):
        edge = bm.edges[edge_index]
        votes = Votes()
        for loop in edge.link_loops:
            # Edge condition votes
            votes += edge_cond_vote(DirectedLoop(loop, True))
            votes += edge_cond_vote(DirectedLoop(loop, False))
            # Face condition votes
            votes += face_cond_vote(DirectedLoop(loop, True))
            votes += face_cond_vote(DirectedLoop(loop, False))
            # Vert condition votes
            votes += vert_cond_vote(DirectedLoop(loop, True))
            votes += vert_cond_vote(DirectedLoop(loop, False))

        return votes

    # Initialize
    frontier = set()
    coloring = [None] * len(bm.edges)
    cached_votes = {}

    def color_edge(edge, twist):
        if edge.index in frontier:
            frontier.remove(edge.index)
        coloring[edge.index] = twist
        for v in edge.verts:
            for other in v.link_edges:
                if coloring[other.index] is None:
                    frontier.add(other.index)
        # Clear cached votes
        cached_votes.pop(edge.index, None)
        for v1 in edge.verts:
            for e2 in v1.link_edges:
                for v2 in e2.verts:
                    if v1.index == v2.index: continue
                    for e3 in v2.link_edges:
                        cached_votes.pop(e3.index, None)

    def get_cached_vote(edge_index):
        if edge_index in cached_votes:
            return cached_votes[edge_index]
        else:
            return cached_votes.setdefault(edge_index, count_votes(edge_index))

    # For each disconnected island of edges
    while True:
        uncolored = [i for i, color in enumerate(coloring) if color is None]
        if not uncolored:
            break

        # Pick a random point
        v0 = choice(bm.edges[choice(uncolored)].verts)

        # Set initial coloring
        for e in v0.link_edges:
            color_edge(e, TWIST_CW)

        # Explore from frontier
        while frontier:
            # First clear out any boundaries from the frontier
            while True:
                found_boundaries = False
                for e in list(frontier):
                    edge = bm.edges[e]
                    if is_boundary(edge.link_loops[0]):
                        color_edge(edge, IGNORE)
                        found_boundaries = True
                if not found_boundaries:
                    break
            # Color the best choice of edge
            votes = {e: get_cached_vote(e) for e in frontier}
            m = max(max(v.cw, v.ccw) for v in votes.values())
            best_edge, best_votes = choice([(k, v) for (k, v) in votes.items() if v.cw == m or v.ccw == m])
            set_twist = TWIST_CW if best_votes.cw > best_votes.ccw else TWIST_CCW
            color_edge(bm.edges[best_edge], set_twist)

    assert all(coloring), "Failed to assign some twists when computing twill"

    return coloring


def get_offset(weave_up, weave_down, twist, forward):
    if twist is TWIST_CW:
        return weave_up if forward else weave_down
    elif twist is TWIST_CCW:
        return weave_down if forward else weave_up
    elif twist is STRAIGHT:
        return (weave_down + weave_up) / 2.0
    else:
        assert False, "Unexpected twist type " + twist


class RibbonBuilder:
    """Builds a mesh containing a polygonal ribbon for each strand."""
    def __init__(self, weave_up, weave_down, length, breadth,
                 strand_analysis=None,
                 materials=None):
        self.weave_up = weave_up
        self.weave_down = weave_down
        self.vertices = []
        self.faces = []
        self.prev_out_verts = None
        self.first_in_verts = None
        self.prev_material = None
        self.c = length
        self.w = breadth
        self.strand_analysis = strand_analysis
        self.uvs = []
        self.materials = materials or defaultdict(int)
        self.material_values = []
        self.count = 0

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
        self.prev_material = None
        self.count = 0

    def add_vertex(self, vert_co, u, v):
        self.vertices.append(vert_co)
        if u is not None and v is not None:
            self.uvs.append((u, v))

    def add_face(self, vertices, material):
        self.faces.append(vertices)
        self.material_values.append(material)

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

        sp = strand_part(prev_loop, loop, forward)
        self.prev_material = material = self.materials[sp]

        if self.strand_analysis:
            strand_index = self.strand_analysis.get_strands()[sp]
            strand_size = self.strand_analysis.get_strand_sizes()[strand_index]
            u1 = (self.count + 0.5 - self.c / 2.0) / strand_size
            u2 = (self.count + 0.5 + self.c / 2.0) / strand_size
        else:
            u1 = None
            u2 = None

        i = len(self.vertices)
        self.add_vertex(v1 + offset, u1, 0)
        self.add_vertex(center1 + offset, u1, 1)
        self.add_vertex(v2 + offset, u2, 1)
        self.add_vertex(center2 + offset, u2, 0)
        # self.add_face([i, i+1, i+2, i+3], material)
        self.add_face([i, i + 1, i + 2], material)
        self.add_face([i, i + 2, i + 3], material)
        in_verts = [i + 1, i + 0]
        out_verts = [i + 3, i + 2]

        if self.first_in_verts is None:
            self.first_in_verts = in_verts
        if self.prev_out_verts is not None:
            self.faces.append(self.prev_out_verts + in_verts)
            self.material_values.append(material)
        self.prev_out_verts = out_verts
        self.count += 1

    def end_strand(self):
        self.faces.append(self.prev_out_verts + self.first_in_verts)
        self.material_values.append(self.prev_material)

    def make_mesh(self):
        me = bpy.data.meshes.new("")
        # Create mesh
        me.from_pydata(self.vertices, [], self.faces)
        # Set materials
        me.polygons.foreach_set("material_index", self.material_values)
        # Set UVs (see https://blender.stackexchange.com/a/8239)
        me.uv_textures.new("")
        uv_layer = me.uv_layers[0]
        uv_layer.data.foreach_set("uv", [uv for pair in [self.uvs[l.vertex_index] for l in me.loops] for uv in pair])
        # Recompute basic values
        me.update(calc_edges=True)
        return me


class BezierBuilder:
    """Builds a bezier object containing a curve for each strand."""
    def __init__(self, bm, crossing_angle, crossing_strength, handle_type, weave_up, weave_down, materials=None):
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
        setup_materials(self.curve.materials, materials)
        # Compute all the midpoints of each edge
        self.midpoints = []
        for e in bm.edges:
            self.midpoints.append(edge_midpoint(e))
        # Per strand stuff
        self.current_spline = None
        self.cos = None
        self.handle_lefts = None
        self.handle_rights = None
        self.first = True
        self.materials = materials or defaultdict(int)
        self.current_material = None

    def start_strand(self):
        self.current_spline = self.curve.splines.new("BEZIER")
        self.current_spline.use_cyclic_u = True
        # Data for the strand
        # It's faster to store in an array and load into blender
        # at once
        self.cos = []
        self.handle_lefts = []
        self.handle_rights = []
        self.current_material = None
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

        self.current_material = self.materials[strand_part(prev_loop, loop, forward)]

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
        self.current_spline.material_index = self.current_material
        if self.handle_type != "AUTO":
            points.foreach_set("handle_left", self.handle_lefts)
            points.foreach_set("handle_right", self.handle_rights)


def visit_strands(bm, twists, builder):
    """Walks over a mesh strand by strand turning at each edge by the specified twists,
    calling visitor methods on the given builder for each edge crossed."""
    # Stores which loops the curve has already passed through
    loops_entered = defaultdict(lambda: False)
    loops_exited = defaultdict(lambda: False)

    # Starting at directed loop, build a curve one vertex at a time
    # until we start where we came from
    # Forward means that for any two edges the loop crosses
    # sharing a face, it is passing through in clockwise order
    # else anticlockwise
    def make_loop(d):
        builder.start_strand()
        while True:
            if d.forward:
                if loops_exited[d.loop]: break
                loops_exited[d.loop] = True
                d = d.next_face_loop
                assert loops_entered[d.loop] == False
                loops_entered[d.loop] = True
                prev_loop = d.loop
                # Find next radial loop
                twist = twists[d.loop.edge.index]
                if twist in (TWIST_CCW, TWIST_CW):
                    d = d.next_edge_loop
            else:
                if loops_entered[d.loop]: break
                loops_entered[d.loop] = True
                d = d.next_face_loop
                assert loops_exited[d.loop] == False
                loops_exited[d.loop] = True
                prev_loop = d.loop
                # Find next radial loop
                twist = twists[d.loop.edge.index]
                if twist in (TWIST_CCW, TWIST_CW):
                    d = d.next_edge_loop
            builder.add_loop(prev_loop, d.loop, twist, d.forward)
        builder.end_strand()

    # Attempt to start a loop at each untouched loop in the entire mesh
    for face in bm.faces:
        for loop in face.loops:
            if is_boundary(loop): continue
            if not loops_exited[loop]: make_loop(DirectedLoop(loop, True))
            if not loops_entered[loop]: make_loop(DirectedLoop(loop, False))


def make_material(name, diffuse):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = diffuse
    mat.diffuse_shader = 'LAMBERT'
    mat.diffuse_intensity = 1.0
    mat.specular_color = (1, 1, 1)
    mat.specular_shader = 'COOKTORR'
    mat.specular_intensity = 0.5
    mat.alpha = 1
    mat.ambient = 1
    return mat


def setup_materials(materials_array, materials):
    if materials is not None:
        materials_array.append(make_material('Red', (1, 0, 0)))
        materials_array.append(make_material('Green', (0, 1, 0)))
        materials_array.append(make_material('Blue', (0, 0, 1)))
        materials_array.append(make_material('Yellow', (1, 1, 0)))
        materials_array.append(make_material('Teal', (0, 1, 1)))
        materials_array.append(make_material('Magenta', (1, 0, 1)))


def create_bezier(context, bm, twists,
                  crossing_angle, crossing_strength, handle_type, weave_up, weave_down, materials):
    builder = BezierBuilder(bm, crossing_angle, crossing_strength, handle_type, weave_up, weave_down, materials)
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


def create_ribbon(context, bm, twists, weave_up, weave_down, length, breadth,
                  strand_analysis, materials):
    builder = RibbonBuilder(weave_up, weave_down, length, breadth, strand_analysis, materials)
    visit_strands(bm, twists, builder)
    mesh = builder.make_mesh()
    orig_obj = context.active_object
    object_utils.object_data_add(context, mesh, operator=None)
    mesh_obj = context.active_object
    context.scene.objects.active = orig_obj

    setup_materials(mesh.materials, materials)

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

    remesh_type = bpy.props.EnumProperty(items=REMESH_TYPES,
                                         name="Remesh Type",
                                         description="Pre-process the mesh before weaving",
                                         default="NONE")

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
    twist_proportion = bpy.props.FloatProperty(name="Twist Proportion",
                                               description="Percent of edges that twist.",
                                               subtype="PERCENTAGE",
                                               unit="NONE",
                                               default=1.0,
                                               min=0.0,
                                               max=1.0)
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
    coloring_types = [("NONE", "None", "No colors"),
                      ("STRAND", "Per strand", "Assign a unique material to every strand."),
                      ("BRAID", "Per braid", "Use as few materials as possible while preserving crossings.")]
    coloring_type = bpy.props.EnumProperty(items=coloring_types,
                                         name="Coloring",
                                         description="Controls what materials are assigned to the created object",
                                         default="NONE")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "remesh_type")
        layout.prop(self, "weave_type")
        layout.prop(self, "weave_up")
        layout.prop(self, "weave_down")
        if self.weave_type == "CELTIC":
            layout.prop(self, "twist_proportion")
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
        layout.prop(self, "coloring_type")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ((ob is not None) and
                (ob.mode == "OBJECT") and
                (ob.type == "MESH") and
                (context.mode == "OBJECT"))

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.new()
        bm.from_mesh(obj.data)

        # Apply remesh if desired
        bm = remesh(bm, self.remesh_type)

        # Compute twists
        if self.weave_type == "CELTIC":
            twists = get_celtic_twists(bm, self.twist_proportion)
        else:
            twists = get_twill_twists(bm)

        # Assign materials to strand parts
        strand_analysis = StrandAnalysisBuilder()
        has_analysis = False

        def get_analysis():
            nonlocal has_analysis
            if not has_analysis:
                visit_strands(bm, twists, strand_analysis)
                has_analysis = True
            return strand_analysis

        if self.coloring_type == "NONE":
            materials = None
        else:
            if self.coloring_type == "STRAND":
                materials = get_analysis().get_strands()
            else:
                materials = get_analysis().get_braids()

        # Build a mesh (or curve) object from the above
        if self.output_type in (BEZIER, PIPE):
            curve_obj = create_bezier(context, bm, twists,
                                      self.crossing_angle,
                                      self.crossing_strength,
                                      self.handle_type,
                                      self.weave_up,
                                      self.weave_down,
                                      materials)

            # If thick, then give it a bevel_object and convert to mesh
            if self.output_type == PIPE and self.thickness > 0:
                create_pipe_from_bezier(context, curve_obj, self.thickness)
        else:
            create_ribbon(context, bm, twists, self.weave_up, self.weave_down, self.length, self.breadth,
                          get_analysis(), materials)
        return {'FINISHED'}


class GeometricRemeshOperator(bpy.types.Operator):
    bl_idname = "object.geometric_remesh_operator"
    bl_label = "Geometric Remesh"
    bl_options = {'REGISTER', 'UNDO'}

    remesh_type = bpy.props.EnumProperty(items=[t for t in REMESH_TYPES if t[0] != "NONE"],
                                         name="Remesh Type",
                                         description="Pre-process the mesh before weaving",
                                         default="EDGE_SUBDIVIDE")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ((ob is not None) and
                (ob.mode == "OBJECT") and
                (ob.type == "MESH") and
                (context.mode == "OBJECT"))

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm = remesh(bm, self.remesh_type)
        bm.to_mesh(obj.data)
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
