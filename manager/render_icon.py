"""Final crown inventory-icon renderer: normal-mapped, bilinear,
high-res supersampled, D2-style top-front key light, ramp toning."""
import xml.etree.ElementTree as ET
import math
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = os.path.dirname(os.path.abspath(__file__))
NS = "http://www.collada.org/2005/11/COLLADASchema"
ns = {"c": NS}

t = ET.parse(os.path.join(S, "crown.dae"))
mesh = next(t.getroot().iter("{%s}geometry" % NS))[0]
tri = mesh.find("c:triangles", ns)
idx = np.array([int(x) for x in tri.find("c:p", ns).text.split()],
               dtype=np.int64)
vv = idx[0::4].reshape(-1, 3)
nn = idx[1::4].reshape(-1, 3)
tg = idx[2::4].reshape(-1, 3)
uvix = idx[3::4].reshape(-1, 3)

def arr(sfx):
    s = [x for x in mesh.findall("c:source", ns)
         if x.get("id").endswith(sfx)][0]
    return np.array([float(v) for v in
                     s.find("c:float_array", ns).text.split()],
                    dtype=np.float32)

P = arr("positions").reshape(-1, 3)
N = arr("normals").reshape(-1, 3)
TG = arr("tangents").reshape(-1, 3)
UV = arr("uvs0").reshape(-1, 2)

band = np.all(UV[uvix][:, :, 1] >= 0.8125, axis=1)
T = vv[band]; TN = nn[band]; TT = tg[band]; TU = uvix[band]

alb = np.asarray(Image.open(os.path.join(S, "crownfl_alb.png"))
                 .convert("L")).astype(np.float32) / 255
nrmim = np.asarray(Image.open(os.path.join(S, "crown_nrm.png"))
                   ).astype(np.float32) / 255
NMX = nrmim[..., 3] * 2 - 1     # DXT5nm: x in alpha
NMY = nrmim[..., 1] * 2 - 1     # y in green
TH, TW = alb.shape

yaw = math.radians(28); tilt = math.radians(16)
Ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0],
               [-math.sin(yaw), 0, math.cos(yaw)]], np.float32)
Rx = np.array([[1, 0, 0], [0, math.cos(tilt), -math.sin(tilt)],
               [0, math.sin(tilt), math.cos(tilt)]], np.float32)
R = Rx @ Ry
V = P @ R.T; NV = N @ R.T; TV = TG @ R.T

bidx = np.unique(T)
mn, mx = V[bidx].min(0), V[bidx].max(0)
c = (mn + mx) / 2
span = max(mx[0] - mn[0], mx[1] - mn[1]) * 1.30
RES = 1176
X = (V[:, 0] - c[0]) / span * RES + RES / 2
Y = RES / 2 - (V[:, 1] - c[1]) / span * RES + RES * 0.02
Z = V[:, 2]

img = np.zeros((RES, RES), np.float32)   # intensity
spec = np.zeros((RES, RES), np.float32)
A = np.zeros((RES, RES), np.float32)
zbuf = np.full((RES, RES), 1e9, np.float32)

L1 = np.array([-0.25, 0.85, -0.45]); L1 /= np.linalg.norm(L1)
VIEW = np.array([0, 0, -1.0])
H1 = L1 + VIEW; H1 /= np.linalg.norm(H1)

def bil(im2, u, v):
    x = u * (TW - 1); y = v * (TH - 1)
    x0 = np.clip(x.astype(int), 0, TW - 2)
    y0 = np.clip(y.astype(int), 0, TH - 2)
    fx = x - x0; fy = y - y0
    return (im2[y0, x0] * (1 - fx) * (1 - fy) + im2[y0, x0 + 1] * fx * (1 - fy)
            + im2[y0 + 1, x0] * (1 - fx) * fy + im2[y0 + 1, x0 + 1] * fx * fy)

for ti in range(len(T)):
    tr = T[ti]; tu = TU[ti]; tn = TN[ti]; tt = TT[ti]
    xs, ys, zs = X[tr], Y[tr], Z[tr]
    x0, x1 = int(max(0, xs.min())), int(min(RES - 1, xs.max()) + 1)
    y0, y1 = int(max(0, ys.min())), int(min(RES - 1, ys.max()) + 1)
    if x1 <= x0 or y1 <= y0:
        continue
    d = ((ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2]))
    if abs(d) < 1e-9:
        continue
    gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
    w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
    w2 = 1 - w0 - w1
    m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not m.any():
        continue
    zz = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
    upd = m & (zz < zbuf[y0:y1, x0:x1])
    if not upd.any():
        continue
    npx = (w0[..., None] * NV[tn[0]] + w1[..., None] * NV[tn[1]]
           + w2[..., None] * NV[tn[2]])
    npx /= np.maximum(np.linalg.norm(npx, axis=-1, keepdims=True), 1e-6)
    flip = npx[..., 2] > 0
    npx[flip] = -npx[flip]
    tpx = (w0[..., None] * TV[tt[0]] + w1[..., None] * TV[tt[1]]
           + w2[..., None] * TV[tt[2]])
    tpx -= npx * (tpx * npx).sum(-1, keepdims=True)
    tpx /= np.maximum(np.linalg.norm(tpx, axis=-1, keepdims=True), 1e-6)
    bpx = np.cross(npx, tpx)
    u = (w0 * UV[tu[0], 0] + w1 * UV[tu[1], 0] + w2 * UV[tu[2], 0]) % 1.0
    vt = 1 - ((w0 * UV[tu[0], 1] + w1 * UV[tu[1], 1]
               + w2 * UV[tu[2], 1]) % 1.0)
    nx = bil(NMX, u, vt); nyv = bil(NMY, u, vt)
    nz = np.sqrt(np.clip(1 - nx * nx - nyv * nyv, 0, 1))
    nper = (tpx * nx[..., None] + bpx * nyv[..., None]
            + npx * nz[..., None])
    nper /= np.maximum(np.linalg.norm(nper, axis=-1, keepdims=True), 1e-6)
    lam = np.maximum((nper * L1).sum(-1), 0)
    sp = np.maximum((nper * H1).sum(-1), 0) ** 55
    tval = bil(alb, u, vt)
    inten = tval * (0.22 + 0.95 * lam)
    ii, jj = np.nonzero(upd)
    img[y0:y1, x0:x1][ii, jj] = inten[ii, jj]
    spec[y0:y1, x0:x1][ii, jj] = sp[ii, jj]
    A[y0:y1, x0:x1][ii, jj] = 1.0
    zbuf[y0:y1, x0:x1][ii, jj] = zz[ii, jj]

# C_bronze ramp
sh = np.array((0.11, 0.07, 0.03))
mi = np.array((0.55, 0.40, 0.18))
hi = np.array((0.95, 0.78, 0.42))
tmap = np.clip(img, 0, 1) ** 1.15
col = np.where(tmap[..., None] < 0.5,
               sh + (mi - sh) * (tmap[..., None] / 0.5),
               mi + (hi - mi) * ((tmap[..., None] - 0.5) / 0.5))
col += hi * spec[..., None] * 0.9
col = np.clip(col, 0, 1)
out = np.concatenate([col * 255, (A * 255)[..., None]], -1).astype(np.uint8)
im = Image.fromarray(out)
al = im.split()[3]
edge = al.filter(ImageFilter.MaxFilter(9))
outline = Image.new("RGBA", (RES, RES), (10, 6, 3, 255))
comp = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))
comp.paste(outline, (0, 0), edge)
comp.alpha_composite(im)
shd = Image.new("L", (RES, RES), 0)
sd = ImageDraw.Draw(shd)
ysh = int(RES * 0.70)
sd.ellipse([RES * 0.20, ysh, RES * 0.80, ysh + RES * 0.11], fill=90)
shd = shd.filter(ImageFilter.GaussianBlur(RES * 0.03))
shadow = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))
shadow.putalpha(shd)
final = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))
final.alpha_composite(shadow)
final.alpha_composite(comp)
final = final.resize((196, 196), Image.LANCZOS)
final.save(os.path.join(S, "coa_icon_render.png"))
bg = Image.new("RGBA", (196, 196), (28, 26, 24, 255))
bg.alpha_composite(final)
bg.convert("RGB").save(os.path.join(S, "coa_icon_on_dark.png"))
print("final render done")
