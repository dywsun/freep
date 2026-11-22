#!/usr/bin/env python3
"""Build a single Worker module for manual Cloudflare dashboard upload."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
assets={'/':(root/'worker-panel/index.html').read_text().replace('href="style.css"','href="/assets/style.css"').replace('src="app.js"','src="/assets/app.js"'),'/assets/style.css':(root/'worker-panel/style.css').read_text(),'/assets/app.js':(root/'worker-panel/app.js').read_text()}
out=root/'worker-service/dist/worker.js';out.parent.mkdir(parents=True,exist_ok=True)
source=(root/'worker-service/src/worker.js').read_text().replace('export async function ', 'async function ').replace('export function ', 'function ')
out.write_text('const RELAY_ASSETS='+json.dumps(assets,ensure_ascii=False)+';\n'+source)
print(out)
