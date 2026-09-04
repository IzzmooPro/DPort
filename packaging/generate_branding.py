"""Render installer layout assets from DPort's existing icon (no logo redesign).

Run: python packaging/generate_branding.py
The 164:314 panel ratio follows Inno Setup's WizardImageFile contract.
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'packaging' / 'assets'


def main():
    OUT.mkdir(exist_ok=True)
    with Image.open(ROOT / 'app/assets/icon.ico') as source:
        logo = source.convert('RGBA')
    panel = Image.new('RGB', (656, 1256), '#101321')
    draw = ImageDraw.Draw(panel)
    for y in range(panel.height):
        t = y / (panel.height - 1)
        draw.line((0, y, panel.width, y), fill=(round(20 - 6*t), round(24 - 7*t), round(43 - 13*t)))
    mark = logo.resize((360, 360), Image.Resampling.LANCZOS)
    panel.paste(mark, (148, 392), mark)
    draw.rectangle((0, 1236, 655, 1255), fill='#6366f1')
    panel.save(OUT / 'wizard-panel.bmp')
    small = Image.new('RGB', (256, 256), 'white')
    mark = logo.resize((208, 208), Image.Resampling.LANCZOS)
    small.paste(mark, (24, 24), mark)
    small.save(OUT / 'wizard-small.bmp')
    # Reviewable asset preview, not a screenshot of a running installer.
    panel.resize((328, 628), Image.Resampling.LANCZOS).save(OUT / 'wizard-panel-preview.png')


if __name__ == '__main__':
    main()
