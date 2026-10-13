#!/usr/bin/python3
"""Opens a picamera2 preview for 4 s with the given preview type, screenshots at 2.5 s."""
import subprocess
import sys
import time

from picamera2 import Picamera2, Preview

kind = sys.argv[1]            # QTGL or QT
shot = sys.argv[2]
cam = Picamera2()
cam.configure(cam.create_preview_configuration(main={"size": (1014, 760)}))
cam.start_preview(getattr(Preview, kind), x=40, y=40, width=640, height=480)
cam.start()
time.sleep(2.5)
subprocess.run(["grim", "-s", "0.5", shot], check=False)
time.sleep(1.5)
cam.close()
print("preview ran OK")
