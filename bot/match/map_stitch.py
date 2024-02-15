from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import os
from core.console import log
from tempfile import NamedTemporaryFile
import math

def map_stitch(maps: list):
    base_url = 'https://raw.githubusercontent.com/vrolse/AQ2-pickup-bot/main/thumbnails/'
    
    # Aspect ratio of images = 1.7
    thumb_size = [800, math.ceil(800/1.7)]
    image_urls = [base_url + name + '.jpg' for name in maps]

    # Download the images and resize
    images = []
    for url in image_urls:
        try:
            image = Image.open(BytesIO(requests.get(url).content))
            image = image.resize((thumb_size[0], thumb_size[1]))
            images.append(image)
        except Exception as e:
            images.append(Image.new('RGB', (thumb_size[0], thumb_size[1])))               

    # Calculate the width and height of the new image
    img_width = max(image.width for image in images)
    img_height = max(image.height for image in images)

    # Calculate needed rows/cols
    img_cnt = len(maps)
    max_cols = 4
    cols = 1
    if img_cnt == 1:
        cols = 1
    else:
        for i in range(2,max_cols+1):
            cols = i if (img_cnt % i == 0) else cols
            cols = i if (img_cnt % i == 1) else cols
            if (cols % i == 0):
                break

    rows = math.ceil(img_cnt / cols)

    # Prefer higher col count
    if (rows > cols):
        tmp = rows
        rows = cols
        cols = tmp

    total_width = img_width * cols
    total_height = img_height * rows

    # Create a new image with the calculated width and height
    new_image = Image.new('RGB', (total_width, total_height))

    # Create a draw object
    draw = ImageDraw.Draw(new_image)

    # Load a system font
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)

    # Paste each image into the new image at the correct position and draw the filename
    try:
        for i, (image, url) in enumerate(zip(images, image_urls)):
            x = i % cols * img_width
            y = i // cols * img_height
            new_image.paste(image, (x, y))            
            # Draw the filename
            filename = os.path.splitext(url.split('/')[-1])[0]  # remove the extension
            text_width = draw.textlength(filename, font=font)
            text_x = x + (img_width - text_width) / 2
            text_y = y
            draw.text((text_x, text_y), filename, fill='white', font=font)
    except Exception as e:
        log.error("\n Error creating map collage: " + str(e) + "\n")

    # Save the new image
    imgfile = NamedTemporaryFile(suffix=".jpg", delete=False)
    new_image.save(imgfile.name)
    return imgfile.name
