"""Генерирует pcspecs.ico (запускать не обязательно — иконка уже в архиве)."""
from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((32, 32, S - 32, S - 32), radius=220, fill=(14, 16, 20, 255), outline=(76, 201, 240, 255), width=24)
c = (76, 201, 240, 255)
# корпус чипа и ножки
d.rounded_rectangle((300, 300, 724, 724), radius=60, outline=c, width=36)
for i in range(4):
    p = 372 + i * 93
    d.rounded_rectangle((p - 18, 190, p + 18, 300), radius=10, fill=c)
    d.rounded_rectangle((p - 18, 724, p + 18, 834), radius=10, fill=c)
    d.rounded_rectangle((190, p - 18, 300, p + 18), radius=10, fill=c)
    d.rounded_rectangle((724, p - 18, 834, p + 18), radius=10, fill=c)
# «пульс» внутри чипа
d.line([(350, 540), (430, 540), (470, 430), (540, 640), (590, 520), (674, 520)], fill=(94, 230, 168, 255), width=34, joint="curve")
img.save("pcspecs.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
img.resize((256, 256), Image.LANCZOS).save("pcspecs_preview.png")
