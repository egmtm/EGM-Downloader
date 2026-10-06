"""Render the main page to disk for the jsdom tests (no server needed)."""
import importlib.util, os, pathlib, sys
os.environ.setdefault("EGM_DEV_MODE", "1")
root = pathlib.Path(__file__).resolve().parents[2]
os.chdir(root)  # app resolves templates/static relative to the repo root
spec = importlib.util.spec_from_file_location("egm", root / "app.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
html = m.app.test_client().get("/").get_data(as_text=True)
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/egm_rendered_index.html")
out.write_text(html, encoding="utf-8")
print(f"rendered {len(html)} bytes -> {out}")

# The Subscriptions window is its own page; render it next to the main page
# (<name>_subs.html) so its tests need no extra step.
subs = m.app.test_client().get("/subscriptions-page").get_data(as_text=True)
subs_out = out.with_name(out.stem + "_subs" + out.suffix)
subs_out.write_text(subs, encoding="utf-8")
print(f"rendered {len(subs)} bytes -> {subs_out}")
