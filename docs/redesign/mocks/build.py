"""Builds the single-file mock (dist/foresprint-mocks.html) from src/.

Fonts are inlined as data URIs because the artifact viewer only allows Google Fonts as a font host.
Usage: python3 build.py
"""

import base64
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"

FACES = [
    ("Iosevka Aile", 400, "iosevka-aile-latin-400.woff2"),
    ("Iosevka Aile", 600, "iosevka-aile-latin-600.woff2"),
    ("Iosevka", 400, "iosevka-latin-400.woff2"),
    ("Iosevka", 600, "iosevka-latin-600.woff2"),
]


def main() -> None:
    def face(name: str, weight: int, file: str) -> str:
        data = base64.b64encode((SRC / "fonts" / file).read_bytes()).decode()
        return (
            f'@font-face{{font-family:"{name}";font-weight:{weight};font-style:normal;'
            f'font-display:swap;src:url(data:font/woff2;base64,{data}) format("woff2")}}'
        )

    fonts = "\n".join(face(*f) for f in FACES)
    js_files = [SRC / "data.js", SRC / "app.js", *sorted((SRC / "views").glob("*.js"))]
    js = "\n".join(f"// ---- {p.relative_to(SRC)}\n{p.read_text()}" for p in js_files)
    html = (SRC / "index.src.html").read_text()
    css = (SRC / "base.css").read_text()
    html = html.replace("/*FONTS*/", fonts).replace("/*CSS*/", css).replace("/*JS*/", js)
    out = ROOT / "dist" / "foresprint-mocks.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(out, len(html) // 1024, "KB")


if __name__ == "__main__":
    main()
