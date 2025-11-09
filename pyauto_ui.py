# pyauto_ui.py
import time
import pyautogui

pyautogui.FAILSAFE = True  # дернул мышь в угол — всё стоп

def move_and_click(x: int, y: int, delay: float = 0.2):
    """
    Двигаем мышь и кликаем в указанные координаты.
    Координаты в пикселях, относительно главного монитора.
    """
    time.sleep(delay)
    pyautogui.moveTo(x, y, duration=0.25)
    pyautogui.click()
