bl_info = {
    "name": "Celtic",
    "description": "",
    "author": "Adam Newgas",
    "version": (0,0),
    "blender": (2, 68, 0),
    "location": "View3D > Add > Mesh",
    "warning": "", # used for warning icon and text in addons panel
    "wiki_url": "http://wiki.blender.org/index.php/Extensions:2.5/Py/"
                "Scripts/My_Script",
    "category": "Add Mesh"}

import bpy
import bmesh
from collections import defaultdict
from mathutils import Vector
from math import pi,sin,cos

class CelticOperator(bpy.types.Operator):
    bl_idname = "object.celtic_operator"
    bl_label = "Celtic Operator"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}

    weave_up = bpy.props.FloatProperty(name="Weave Up",
                                       description="Distance to shift curve upwards over knots",
                                       subtype="DISTANCE",
                                       unit="LENGTH")
    weave_down = bpy.props.FloatProperty(name="Weave Down",
                                         description="Distance to shift curve downward under knots",
                                         subtype="DISTANCE",
                                         unit="LENGTH")
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

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.mode == 'OBJECT' and obj.type == "MESH"

    def execute(self, context):
        s = sin(self.crossing_angle) * self.crossing_strength
        c = cos(self.crossing_angle) * self.crossing_strength
        obj = context.active_object
        curve = bpy.data.curves.new("Celtic","CURVE")
        curve.dimensions = "3D"
        curve.twist_mode = "MINIMUM"
        obj = obj.data
        midpoints = []
        # Compute all the midpoints of each edge
        for e in obj.edges.values():
            v1 = obj.vertices[e.vertices[0]]
            v2 = obj.vertices[e.vertices[1]]
            m = tuple((v1.co[i]+v2.co[i])/2 for i in range(3))
            midpoints.append(m)

        bm = bmesh.new()
        bm.from_mesh(obj)
        # Stores which loops the curve has already passed through
        loops_entered = defaultdict(lambda:False)
        loops_exited = defaultdict(lambda:False)
        # Loops on the boundary of a surface
        def ignorable_loop(loop):
            return len(loop.link_loops)==0
        # Starting at loop, build a curve one vertex at a time
        # until we start where we came from
        # Forward means that for any two edges the loop crosses
        # sharing a face, it is passing through in clockwise order
        # else anticlockwise
        def make_loop(loop, forward):
            current_spline = curve.splines.new("BEZIER")
            current_spline.use_cyclic_u = True
            first = True
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
                    assert loop.link_loops[-1] != loop
                    loop = loop.link_loops[-1]
                    forward = loop.vert.index == v
                if not first:
                    current_spline.bezier_points.add()
                first = False
                point = current_spline.bezier_points[-1]
                midpoint = Vector(midpoints[loop.edge.index])
                normal = loop.calc_normal() + prev_loop.calc_normal()
                normal.normalize()
                tangent = loop.link_loop_next.vert.co - loop.vert.co
                tangent.normalize()
                binormal = normal.cross(tangent).normalized()
                if not forward: tangent *= -1
                offset = self.weave_up if forward else self.weave_down
                midpoint += offset * normal
                point.co = midpoint
                point.handle_left_type = self.handle_type
                point.handle_right_type = self.handle_type
                point.handle_left = midpoint - s * binormal - c * tangent
                point.handle_right = midpoint + s * binormal + c * tangent

        # Attempt to start a loop at each untouched loop in the entire mesh
        for face in bm.faces:
            for loop in face.loops:
                if ignorable_loop(loop): continue
                if not loops_exited[loop]: make_loop(loop, True)
                if not loops_entered[loop]: make_loop(loop, False)
        # Create an object from the curve
        from bpy_extras import object_utils
        object_utils.object_data_add(context, curve, operator=None)
        curve_obj = context.active_object
        # If thick, then give it a bevel_object and convert to mesh
        if self.thickness > 0:
            bpy.ops.curve.primitive_bezier_circle_add()
            bpy.ops.transform.resize(value=(self.thickness,)*3)
            circle = context.active_object
            curve.bevel_object = circle
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
        return {'FINISHED'}

def register():
    bpy.utils.register_class(CelticOperator)

if __name__ == "__main__":
    register()
