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

    def execute(self, context):
        context.active_object.location.x += 1.0
        return {'FINISHED'}

def register():
    bpy.utils.register_class(CelticOperator)

if __name__ == "__main__":
    register()
