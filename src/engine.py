import numpy as np
import random

shapes = {
    'T': [(0, 0), (-1, 0), (1, 0), (0, -1)],
    'J': [(0, 0), (-1, 0), (0, -1), (0, -2)],
    'L': [(0, 0), (1, 0), (0, -1), (0, -2)],
    'Z': [(0, 0), (-1, 0), (0, -1), (1, -1)],
    'S': [(0, 0), (-1, -1), (0, -1), (1, 0)],
    'I': [(0, 0), (0, -1), (0, -2), (0, -3)],
    'O': [(0, 0), (0, -1), (-1, 0), (-1, -1)],
}
shape_names = ['T', 'J', 'L', 'Z', 'S', 'I', 'O']


def rotated(shape, cclk=False):
    if cclk:
        return [(-j, i) for i, j in shape]
    else:
        return [(j, -i) for i, j in shape]


def is_occupied(shape, anchor, board):
    for i, j in shape:
        x, y = anchor[0] + i, anchor[1] + j
        if y < 0:
            continue
        if x < 0 or x >= board.shape[0] or y >= board.shape[1] or board[x, y]:
            return True
    return False


def left(shape, anchor, board):
    new_anchor = (anchor[0] - 1, anchor[1])
    return (shape, anchor) if is_occupied(shape, new_anchor, board) else (shape, new_anchor)


def right(shape, anchor, board):
    new_anchor = (anchor[0] + 1, anchor[1])
    return (shape, anchor) if is_occupied(shape, new_anchor, board) else (shape, new_anchor)


def soft_drop(shape, anchor, board):
    new_anchor = (anchor[0], anchor[1] + 1)
    return (shape, anchor) if is_occupied(shape, new_anchor, board) else (shape, new_anchor)


def hard_drop(shape, anchor, board):
    while True:
        _, anchor_new = soft_drop(shape, anchor, board)
        if anchor_new == anchor:
            return shape, anchor_new
        anchor = anchor_new


def rotate_left(shape, anchor, board):
    new_shape = rotated(shape, cclk=False)
    return (shape, anchor) if is_occupied(new_shape, anchor, board) else (new_shape, anchor)


def rotate_right(shape, anchor, board):
    new_shape = rotated(shape, cclk=True)
    return (shape, anchor) if is_occupied(new_shape, anchor, board) else (new_shape, anchor)


def idle(shape, anchor, board):
    return (shape, anchor)


class TetrisEngine:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.board = np.zeros(shape=(width, height), dtype=np.float)

        # actions are triggered by letters
        self.value_action_map = {
            0: left,
            1: right,
            2: hard_drop,
            3: soft_drop,
            4: rotate_left,
            5: rotate_right,
            6: idle,
            7: self.hold,
        }
        self.action_value_map = dict([(j, i) for i, j in self.value_action_map.items()])
        self.nb_actions = len(self.value_action_map)

        # for running the engine
        self.time = -1
        self.score = -1
        self.anchor = None
        self.shape = None
        self.shape_name = None
        self.n_deaths = 0

        # states
        self.total_cleared_lines = 0
        self.previous_bomb_lines = 0
        self.bomb_lines = 0
        self.highest_line = 0
        self.drop_count = 0
        self.step_num_to_drop = 3
        self.holded = False
        self.hold_shape = []
        self.hold_shape_name = None

        # used for generating shapes
        self._shape_counts = [0] * len(shapes)

        # clear after initializing
        self.clear()

    def _choose_shape(self):
        maxm = max(self._shape_counts)
        m = [5 + maxm - x for x in self._shape_counts]
        r = random.randint(1, sum(m))
        for i, n in enumerate(m):
            r -= n
            if r <= 0:
                self._shape_counts[i] += 1
                return shape_names[i], shapes[shape_names[i]]

    def _new_piece(self):
        # Place randomly on x-axis with 2 tiles padding
        self.anchor = (self.width // 2, 1)
        self.shape_name, self.shape = self._choose_shape()

    def _has_dropped(self):
        return is_occupied(self.shape, (self.anchor[0], self.anchor[1] + 1), self.board)

    def _clear_lines(self):
        can_clear = [True if sum(self.board[:, i]) == self.width else False for i in range(self.height)]
        new_board = np.zeros_like(self.board)
        j = self.height - 1
        for i in range(self.height - 1, -1, -1):
            if not can_clear[i]:
                new_board[:, j] = self.board[:, i]
                j -= 1
        self.score += sum(can_clear)
        self.board = new_board

        return sum(can_clear)

    def valid_action_count(self):
        valid_action_sum = 0

        for value, fn in self.value_action_map.items():
            if value == 7:
                continue
            # If they're equal, it is not a valid action
            if fn(self.shape, self.anchor, self.board) != (self.shape, self.anchor):
                valid_action_sum += 1

        return valid_action_sum

    def step(self, action):
        self.anchor = (self.anchor[0], self.anchor[1])
        self.shape, self.anchor = self.value_action_map[action](self.shape, self.anchor, self.board)

        reward = self.valid_action_count()

        # Drop each 3 step
        done = False
        cleared_lines = 0
        if self.drop_count == self.step_num_to_drop or action == 2:
            self.drop_count = 0
            if action != 3:
                self.shape, self.anchor = soft_drop(self.shape, self.anchor, self.board)
            if self._has_dropped():
                self._set_piece(True)
                cleared_lines = self._clear_lines()
                self.total_cleared_lines += cleared_lines
                reward += cleared_lines * 10
                if np.any(self.board[:, 0]):
                    self.clear()
                    self.n_deaths += 1
                    if self.bomb_lines == 0:
                        done = True
                    reward = -10
                else:
                    self._new_piece()
                    self.holded = False

        # Update time and reward
        self.time += 1
        self.drop_count += 1

        self._set_piece(True)
        state = np.copy(self.board)
        self._set_piece(False)
        self._update_states()
        return state, reward, done, cleared_lines

    def clear(self):
        self._new_piece()
        self.holded = False
        self.bomb_lines = 0
        self.highest_line = 0

        return self.board

    def _set_piece(self, on=False):
        for i, j in self.shape:
            x, y = i + self.anchor[0], j + self.anchor[1]
            if x < self.width and x >= 0 and y < self.height and y >= 0:
                self.board[self.anchor[0] + i, self.anchor[1] + j] = on

    def __repr__(self):
        self._set_piece(True)
        s = f"Hold: {self.hold_shape_name}\n"
        s += 'o' + '-' * self.width + 'o'
        for line in self.board.T[1:]:
            display_line = ['\n|']
            for grid in line:
                if grid == -1:
                    display_line.append('X')
                elif grid:
                    display_line.append('O')
                else:
                    display_line.append(' ')
            display_line.append('|')
            s += "".join(display_line)

        s += '\no' + '-' * self.width + 'o\n'
        self._set_piece(False)
        return s

    def receive_bomb_lines(self, bomb_lines):
        self.bomb_lines += bomb_lines

    def is_alive(self):
        if self.highest_line >= self.height:
            return False
        return True

    def _update_states(self):
        new_board = np.zeros_like(self.board)
        if self.bomb_lines > 0:
            new_board[:, -self.bomb_lines:] = -1
        for i in range(self.height - self.previous_bomb_lines - 1, -1, -1):
            new_board[:, i - (self.bomb_lines - self.previous_bomb_lines)] = self.board[:, i]
        self.previous_bomb_lines = self.bomb_lines
        self.board = new_board
        for i in range(self.height - 1, -1, -1):
            if sum(self.board[:, i]) > 0:
                self.highest_line = self.height - i

    def hold(self, shape, anchor, board):
        if self.holded:
            return (shape, anchor)
        else:
            self.holded = True
            tmp_shape_name = self.shape_name
            if len(self.hold_shape) == 0:
                self._new_piece()
            else:
                self.shape = self.hold_shape
                self.shape_name = self.hold_shape_name
            self.hold_shape = shape
            self.hold_shape_name = tmp_shape_name
        return (self.shape, self.anchor)
