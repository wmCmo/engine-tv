"""Net helper process for the Net explorer page.

Started on demand by lc0viz.py with the project venv (`.venv`, see requirements-net.txt):

    .venv/Scripts/python networker.py prepare <lc0.exe> <weights file> <out.onnx>
    .venv/Scripts/python networker.py serve <out.onnx>

`prepare` converts the weights with lc0's own `leela2onnx` and exposes the internal tensors
(per-layer residual stream, feed-forward neurons, attention maps, policy from/to map) as extra
graph outputs. `serve` loads the model (~725 MB of RAM for a BT4-size net on the CPU), answers JSON
requests on stdin/stdout, and exits after IDLE_EXIT seconds without a request so the memory goes
back to the system (ONNX Runtime doesn't return it while the process lives).
"""
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import OrderedDict

IDLE_EXIT = int(os.environ.get("LC0VIZ_NET_IDLE", "300"))  # seconds without a request before exiting


# ------------------------------------------------------------------ prepare

def prepare(lc0, weights, out):
    import onnx
    from onnx import TensorProto, helper

    tmp = out + ".plain.onnx"
    p = subprocess.run([lc0, "leela2onnx", f"--input={weights}", f"--output={tmp}"],
                       capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0 or not os.path.exists(tmp):
        raise SystemExit("leela2onnx failed: " + (p.stdout + p.stderr)[-800:])
    model = onnx.load(tmp)
    names = {o for n in model.graph.node for o in n.output}
    layers = sorted({int(m.group(1)) for n in names for m in [re.match(r"/encoder(\d+)/", n)] if m})
    want = ["/attn_body/ln2", "/policy/scale"]
    for i in layers:
        want += [f"/encoder{i}/ln2", f"/encoder{i}/ffn/dense1/mish", f"/encoder{i}/mha/QK/softmax"]
    missing = [w for w in want if w not in names]
    if missing:
        raise SystemExit(f"net layout not recognised, missing {missing[:4]}")
    have = {o.name for o in model.graph.output}
    for w in want:
        if w not in have:
            model.graph.output.append(helper.make_tensor_value_info(w, TensorProto.FLOAT, None))
    onnx.save(model, out + ".part")
    os.replace(out + ".part", out)
    os.remove(tmp)
    print(json.dumps({"ok": True, "layers": len(layers)}), flush=True)


# ------------------------------------------------------------------ serve

class Net:
    def __init__(self, path):
        import numpy as np
        import onnxruntime as ort
        self.np = np
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)  # leave CPU for everything else
        self.sess = ort.InferenceSession(path, opt, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        self.out_names = [o.name for o in self.sess.get_outputs()]
        self.layers = sorted({int(m.group(1)) for n in self.out_names for m in [re.match(r"/encoder(\d+)/ln2$", n)] if m})
        self.cache = OrderedDict()  # key -> dict of arrays

    def eval(self, key, planes_b64):
        np = self.np
        x = np.frombuffer(base64.b64decode(planes_b64), dtype=np.float32).reshape(1, 112, 8, 8)
        t = time.perf_counter()
        raw = dict(zip(self.out_names, self.sess.run(None, {self.inp: x})))
        ms = (time.perf_counter() - t) * 1000
        L = len(self.layers)
        resid = np.stack([raw["/attn_body/ln2"].reshape(64, -1)] +
                         [raw[f"/encoder{i}/ln2"].reshape(64, -1) for i in self.layers])            # (L+1, 64, D)
        ffn = np.stack([raw[f"/encoder{i}/ffn/dense1/mish"].reshape(64, -1) for i in self.layers])   # (L, 64, F)
        attn = np.stack([raw[f"/encoder{i}/mha/QK/softmax"].reshape(-1, 64, 64) for i in self.layers])  # (L, H, 64, 64)
        pmap = raw["/policy/scale"].reshape(64, 64)
        d = {"resid": resid, "ffn": ffn, "attn": attn, "pmap": pmap}
        self.cache[key] = d
        while len(self.cache) > 3:
            self.cache.popitem(last=False)
        ent = -(attn * np.log(attn + 1e-12)).sum(-1).mean(-1)  # (L, H): mean attention entropy over queries
        return {
            "ms": round(ms, 1),
            "policy": raw["/output/policy"].reshape(-1).tolist(),
            "wdl": raw["/output/wdl"].reshape(-1).tolist(),
            "mlh": float(raw["/output/mlh"].reshape(-1)[0]),
            "layers": L, "heads": attn.shape[1], "d_model": resid.shape[2], "d_ffn": ffn.shape[2],
            "resid_norm": np.linalg.norm(resid, axis=2).round(3).tolist(),          # (L+1, 64)
            # how much each layer changed each square's representation (LayerNorm keeps sizes ~flat,
            # so the change is the informative quantity)
            "resid_delta": np.linalg.norm(resid[1:] - resid[:-1], axis=2).round(3).tolist(),  # (L, 64)
            "ffn_active": (ffn > 0.5).mean(axis=2).round(4).tolist(),               # (L, 64) share of neurons firing
            "ffn_mean": ffn.mean(axis=2).round(4).tolist(),
            "attn_entropy": ent.round(3).tolist(),                                   # (L, H)
        }

    def get(self, key):
        if key not in self.cache:
            raise KeyError("position not loaded; evaluate it first")
        self.cache.move_to_end(key)
        return self.cache[key]

    def neuron(self, key, kind, layer, neuron):
        a = self.get(key)[kind][layer][:, neuron]
        return {"values": a.round(4).tolist()}

    def top(self, key, kind, layer, token, k=24):
        np = self.np
        row = self.get(key)[kind][layer][token]
        idx = np.argsort(-row)[:k]
        return {"top": [[int(i), round(float(row[i]), 4)] for i in idx]}

    def attn(self, key, layer, token):
        a = self.get(key)["attn"][layer][:, token, :]  # (H, 64): where each head looks from this square
        return {"heads": a.round(4).tolist()}

    def pmap(self, key, token):
        return {"values": self.get(key)["pmap"][token].round(3).tolist()}


def serve(path):
    last = [time.time()]

    def watchdog():
        while True:
            time.sleep(5)
            if time.time() - last[0] > IDLE_EXIT:
                os._exit(0)
    threading.Thread(target=watchdog, daemon=True).start()
    t = time.perf_counter()
    net = Net(path)
    # report our own pid: on Windows a venv's python.exe is a launcher that runs the real interpreter as a child
    print(json.dumps({"ready": True, "pid": os.getpid(), "load_s": round(time.perf_counter() - t, 1),
                      "layers": len(net.layers)}), flush=True)
    for line in sys.stdin:
        last[0] = time.time()
        try:
            req = json.loads(line)
            op = req.pop("op")
            if op == "ping":
                res = {"pong": True}
            elif op == "quit":
                os._exit(0)
            else:
                res = getattr(net, op)(**req)
            out = {"ok": True, **res}
        except Exception as e:
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
        last[0] = time.time()


if __name__ == "__main__":
    if sys.argv[1] == "prepare":
        prepare(*sys.argv[2:5])
    elif sys.argv[1] == "serve":
        serve(sys.argv[2])
