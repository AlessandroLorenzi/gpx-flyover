"""Script eseguito DENTRO Blender: costruisce la scena da scene.npz e renderizza i fotogrammi.

Uso: blender -b --factory-startup --python blender_render.py -- WORKDIR WIDTH HEIGHT SAMPLES
"""

import math
import sys

import bpy
import numpy as np
from mathutils import Vector

workdir, width, height, samples = sys.argv[sys.argv.index("--") + 1 :]
S = np.load(f"{workdir}/scene.npz")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene


def grid_mesh(name, Z, ext):
    """Mesh a griglia con UV 0..1 da una matrice di quote. ext = x0, x1, y0, y1 (y0 = bordo nord)."""
    x0, x1, y0, y1 = ext
    R, C = Z.shape
    X, Y = np.meshgrid(np.linspace(x0, x1, C), np.linspace(y0, y1, R))
    verts = np.c_[X.ravel(), Y.ravel(), Z.ravel()].astype(np.float32)
    ii = np.arange(R * C).reshape(R, C)
    quads = np.c_[ii[:-1, :-1].ravel(), ii[1:, :-1].ravel(), ii[1:, 1:].ravel(), ii[:-1, 1:].ravel()]
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.ravel())
    me.loops.add(quads.size)
    me.loops.foreach_set("vertex_index", quads.ravel().astype(np.int32))
    me.polygons.add(len(quads))
    me.polygons.foreach_set("loop_start", np.arange(0, quads.size, 4, dtype=np.int32))
    me.update()
    UU, VV = np.meshgrid(np.linspace(0, 1, C), np.linspace(1, 0, R))
    me.uv_layers.new(name="UV").data.foreach_set("uv", np.c_[UU.ravel(), VV.ravel()][quads.ravel()].ravel().astype(np.float32))
    me.polygons.foreach_set("use_smooth", np.ones(len(quads), dtype=bool))
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    return ob


def image_material(name, path):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 1.0
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(path)
    tex.extension = "EXTEND"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return m


def emissive(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Emission Color"].default_value = (*color, 1)
    b.inputs["Emission Strength"].default_value = strength
    return m


# terreno
grid_mesh("terrain", S["Z"], S["ext"]).data.materials.append(image_material("sat", f"{workdir}/sat_inner.jpg"))
grid_mesh("outer", S["Zo"], S["exto"]).data.materials.append(image_material("sat_o", f"{workdir}/sat_outer.jpg"))

# traccia: una curva per pezzo (i pezzi sono separati da uno stacco), il cui bevel_factor_end
# anima il "disegno" progressivo
tr = S["track"]
starts = [int(b) for b in S["breaks"]] if "breaks" in S else [0]
spans = list(zip(starts, starts[1:] + [len(tr)]))
trk_mat = emissive("trk", (1, 0.13, 0.02), 2.0)
curves = []
for n, (a, b) in enumerate(spans):
    cu = bpy.data.curves.new(f"track{n}", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(b - a - 1)
    sp.points.foreach_set("co", np.c_[tr[a:b], np.ones(b - a)].ravel().astype(np.float32))
    cu.bevel_depth = 4.5
    cu.bevel_resolution = 2
    cu.use_fill_caps = True
    cu.bevel_factor_mapping_end = "SPLINE"
    cu.materials.append(trk_mat)
    ob = bpy.data.objects.new(f"track{n}", cu)
    sc.collection.objects.link(ob)
    curves.append((ob, cu, a, b))

bpy.ops.mesh.primitive_uv_sphere_add(radius=12)
marker = bpy.context.active_object
marker.data.materials.append(emissive("marker", (1, 0.82, 0.1), 4.0))

# luce e cielo
sun = bpy.data.lights.new("sun", "SUN")
sun.energy = 4.0
sun.angle = math.radians(2)
so = bpy.data.objects.new("sun", sun)
so.rotation_euler = (math.radians(50), 0, math.radians(150))
sc.collection.objects.link(so)
world = bpy.data.worlds.new("world")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.55, 0.68, 0.85, 1)
bg.inputs["Strength"].default_value = 0.9
sc.world = world

# telecamera e animazione
cd = bpy.data.cameras.new("cam")
cd.lens = 24
cd.clip_start = 5
cd.clip_end = 120000
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam

CAM, LOOK, REV = S["cam"], S["look"], S["reveal"]
# Il bevel factor in modalità SPLINE è proporzionale alla lunghezza 3D, mentre pallina e
# telecamera avanzano per indice di punto (passo costante in pianta): si converte l'uno nell'altro
# così la testa della linea coincide con la pallina anche in salita.
d3 = [np.r_[0, np.cumsum(np.linalg.norm(np.diff(tr[a:b], axis=0), axis=1))] for _, _, a, b in curves]
for f in range(len(CAM)):
    fr = f + 1
    cam.location = Vector(CAM[f])
    cam.rotation_euler = (Vector(LOOK[f]) - Vector(CAM[f])).to_track_quat("-Z", "Y").to_euler()
    cam.keyframe_insert("location", frame=fr)
    cam.keyframe_insert("rotation_euler", frame=fr)
    k = REV[f] * (len(tr) - 1)
    for (ob, cu, a, b), d in zip(curves, d3):
        ob.hide_render = bool(k < a)  # il pezzo non è ancora iniziato
        ob.keyframe_insert("hide_render", frame=fr)
        loc = np.interp(min(max(k - a, 0), b - a - 1), np.arange(b - a), d) / max(d[-1], 1e-6)
        cu.bevel_factor_end = max(float(loc), 1e-4)
        cu.keyframe_insert("bevel_factor_end", frame=fr)
    i = int(k)
    j = i + 1 if i + 1 < len(tr) and i + 1 not in starts else i  # non si attraversa il salto
    marker.location = Vector(tr[i] * (1 - (k - i)) + tr[j] * (k - i)) + Vector((0, 0, 6))
    marker.keyframe_insert("location", frame=fr)

# render
engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_EEVEE_NEXT"
sc.eevee.taa_render_samples = int(samples)
sc.render.resolution_x = int(width)
sc.render.resolution_y = int(height)
sc.render.fps = int(S["fps"])
sc.frame_start = 1
sc.frame_end = len(CAM)
try:
    sc.view_settings.view_transform = "Standard"
except TypeError:
    pass
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = f"{workdir}/frames/f_"
bpy.ops.render.render(animation=True)
