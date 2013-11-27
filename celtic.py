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

class CelticOperator(bpy.types.Operator):
    bl_idname = "object.celtic_operator"
    bl_label = "Celtic Operator"

    total = bpy.props.IntProperty(name="Steps", default=2, min=1, max=100)

    def execute(self, context):
        obj = context.active_object
        assert obj.type == "MESH"
        mesh = bpy.data.meshes.new("Celtic")
        obj = obj.data
        verts = []
        edges = []
        faces = []
        for e in obj.edges.values():
            v1 = obj.vertices[e.vertices[0]]
            v2 = obj.vertices[e.vertices[1]]
            m = tuple((v1.co[i]+v2.co[i])/2 for i in range(3))
            verts.append(m)
        for f in obj.polygons.values():
            #assert len(f.vertices) == 3, repr(f.vertices)
            fout = []
            for i in range(f.loop_start,f.loop_start+f.loop_total):
                n = i+1
                if n == f.loop_start+f.loop_total: n = f.loop_start
                l1 = obj.loops[i]
                l2 = obj.loops[n]
                edges.append((l1.edge_index,l2.edge_index))
                fout.append(l1.edge_index)
            #faces.append(fout)

        mesh.from_pydata(verts, edges, faces)
        mesh.update()
        from bpy_extras import object_utils
        object_utils.object_data_add(context, mesh, operator=None)
        return {'FINISHED'}

def register():
    bpy.utils.register_class(CelticOperator)

if __name__ == "__main__":
    register()
