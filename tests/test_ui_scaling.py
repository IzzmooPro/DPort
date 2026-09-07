"""Pure layout regression tests: no application startup or network changes."""
import ast
import math
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'app' / 'gui' / 'app.py'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
NAMES = {'_content_height', '_physical_size', '_place_beside_top'}
SCOPE = {'math': math}
exec(compile(ast.Module(body=[n for n in TREE.body
                             if isinstance(n, ast.FunctionDef) and n.name in NAMES],
                        type_ignores=[]), str(SOURCE), 'exec'), SCOPE)


class Window:
    def __init__(self, scale, screen=(1920, 1080)):
        self.scale, self.screen = scale, screen
    def _reverse_window_scaling(self, value): return value / self.scale
    def _apply_window_scaling(self, value): return round(value * self.scale)
    def winfo_reqheight(self): return round(440 * self.scale)
    def update_idletasks(self): pass
    def winfo_screenwidth(self): return self.screen[0]
    def winfo_screenheight(self): return self.screen[1]
    def winfo_x(self): return self.screen[0] - 450
    def winfo_y(self): return self.screen[1] - 200
    def winfo_width(self): return 435
    def geometry(self, value): self.last_geometry = value


class ScalingTests(unittest.TestCase):
    def test_requested_pixels_are_unscaled_exactly_once(self):
        for scale in (1, 1.25, 1.5, 1.75, 2, 2.5, 3):
            with self.subTest(scale=scale):
                win = Window(scale)
                height = SCOPE['_content_height'](win)
                self.assertEqual(height, 446)
                self.assertLessEqual(abs(win._apply_window_scaling(height)
                                         - win.winfo_reqheight() - 6 * scale), 1)

    def test_docked_position_uses_physical_bounds(self):
        for scale in (1, 1.25, 1.5, 2):
            for screen in ((1024, 768), (1280, 720), (1280, 800), (1360, 768),
                           (1366, 768), (1440, 900), (1600, 900), (1680, 1050),
                           (1920, 1080), (1920, 1200), (2560, 1080),
                           (2560, 1440), (3440, 1440), (3840, 2160)):
                with self.subTest(scale=scale, screen=screen):
                    win = Window(scale, screen)
                    x, y = SCOPE['_place_beside_top'](win, win, 300, 300)
                    pw, ph = SCOPE['_physical_size'](win, 300, 300)
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x + pw, screen[0])
                    self.assertLessEqual(y + ph, screen[1])


if __name__ == '__main__':
    unittest.main()
