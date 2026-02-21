#!/usr/bin/env python3
import sys
import pygame


def main():
    pygame.init()
    pygame.joystick.init()

    screen = pygame.display.set_mode((520, 600))
    pygame.display.set_caption('Joystick Index Checker')
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 22)

    joysticks: dict[int, pygame.joystick.Joystick] = {}

    BG = (13, 17, 23)
    HEADER = (88, 166, 255)
    DIM = (139, 148, 158)
    ACTIVE = (63, 185, 80)
    PRESSED = (248, 81, 73)
    WHITE = (201, 209, 217)

    def text(surface, msg, x, y, color=WHITE):
        surface.blit(font.render(msg, True, color), (x, y))

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q:
                running = False
            if event.type == pygame.JOYDEVICEADDED:
                joy = pygame.joystick.Joystick(event.device_index)
                joysticks[joy.get_instance_id()] = joy
                print(f'[+] Joystick {joy.get_instance_id()}: {joy.get_name()}')
            if event.type == pygame.JOYDEVICEREMOVED:
                joysticks.pop(event.instance_id, None)
                print(f'[-] Joystick {event.instance_id} disconnected')

        screen.fill(BG)
        y = 10

        if not joysticks:
            text(screen, 'No joystick detected...', 10, y, DIM)
        else:
            for joy in joysticks.values():
                text(screen, f'[{joy.get_instance_id()}] {joy.get_name()}', 10, y, HEADER)
                y += 22

                num_axes = joy.get_numaxes()
                text(screen, f'Axes ({num_axes})', 10, y, DIM)
                y += 18
                for i in range(num_axes):
                    val = joy.get_axis(i)
                    active = abs(val) > 0.05
                    bar_w = int(abs(val) * 100)
                    color = ACTIVE if active else DIM
                    label = f'  axis {i}: {val:+.3f}'
                    text(screen, label, 10, y, color)
                    if active:
                        bx = 200
                        bw = bar_w
                        pygame.draw.rect(screen, color,
                                         (bx + (0 if val > 0 else -bw), y + 3, bw, 12))
                    y += 18

                y += 4

                num_btns = joy.get_numbuttons()
                text(screen, f'Buttons ({num_btns})', 10, y, DIM)
                y += 18
                cols, col_w = 8, 58
                for i in range(num_btns):
                    pressed = joy.get_button(i)
                    bx = 10 + (i % cols) * col_w
                    by = y + (i // cols) * 22
                    color = PRESSED if pressed else DIM
                    text(screen, f'btn {i}', bx, by, color)
                y += ((num_btns - 1) // cols + 1) * 22 + 8

                num_hats = joy.get_numhats()
                if num_hats:
                    text(screen, f'Hats ({num_hats})', 10, y, DIM)
                    y += 18
                    for i in range(num_hats):
                        hx, hy = joy.get_hat(i)
                        active = hx != 0 or hy != 0
                        text(screen, f'  hat {i}: ({hx:+d}, {hy:+d})',
                             10, y, ACTIVE if active else DIM)
                        y += 18
                    y += 4

        text(screen, 'q : quit', 10, 575, DIM)
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()


if __name__ == '__main__':
    main()
