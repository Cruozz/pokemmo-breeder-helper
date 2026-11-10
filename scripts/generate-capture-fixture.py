"""Build a synthetic four-second OCR recording; contains no user inventory."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", required=True, help="Path to a CJK TrueType/OpenType font")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "android-app/app/src/androidTest/assets/synthetic-inventory.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(args.font, 42)
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        for index, species, ivs in [(0, "蘑蘑菇", "31/2/19/0/16/6"), (1, "伊布", "31/31/20/0/15/6")]:
            image = Image.new("RGB", (1280, 720), "white")
            draw = ImageDraw.Draw(image)
            for row, text in enumerate([f"Lv.1 {species}", "能力值：12/5/6/5/6/5", f"个体值：{ivs}",
                                        "努力值：0/0/0/0/0/0", "性格：坦率 Docile"]):
                draw.text((60, 45 + row * 100), text, font=font, fill="black")
            image.save(directory / f"frame-{index}.png")
        subprocess.run([args.ffmpeg, "-y", "-loglevel", "error", "-framerate", "1/2",
                        "-i", str(directory / "frame-%d.png"), "-c:v", "libx264", "-r", "10",
                        "-pix_fmt", "yuv420p", "-t", "4", "-movflags", "+faststart", str(output)], check=True)
    print(output)


if __name__ == "__main__":
    main()
