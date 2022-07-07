import random
import json

from json import JSONEncoder

from constants import layout_cells

NORMAL = 0
BIG_CELLS = 1


class GridJSONEncoder(JSONEncoder):
    def default(self, o):
        if hasattr(o, "__dict__"):
            return o.__dict__()
        return JSONEncoder.default(self, o)


class GridElement:
    def __init__(self, name, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.name = name
        self.additional_data = {}     # other stuff that will be json serialized along with everything else

    def __dict__(self):
        _dict = {
            **{
                "x": self.x,
                "y": self.y,
                "w": self.w,
                "h": self.h,
                "name": self.name,
            },
            **self.additional_data
        }
        if type(self) in TYPES:
            _dict["type"] = TYPES[type(self)]
        return _dict


class SliderLikeElement(GridElement):
    def __init__(self, name, x, y, w, h, min_value, max_value):
        super(SliderLikeElement, self).__init__(name, x, y, w, h)
        self.min = min_value
        self.max = max_value
        self.value = self.min

    def __dict__(self):
        return {
            **super(SliderLikeElement, self).__dict__(),
            **{
                "min": self.min,
                "max": self.max
            }
        }


class Button(GridElement):
    pass


class Slider(SliderLikeElement):
    pass


class CircularSlider(SliderLikeElement):
    pass


class ButtonsSlider(SliderLikeElement):
    pass


class Actions(GridElement):
    def __init__(self, name, x, y, w, h, actions):
        super(Actions, self).__init__(name, x, y, w, h)
        self.actions = actions

    def __dict__(self):
        return {
            **super(Actions, self).__dict__(),
            **{
                "actions": self.actions
            }
        }


class Switch(GridElement):
    def __init__(self, name, x, y, w, h):
        super(Switch, self).__init__(name, x, y, w, h)
        self.toggled = False

TYPES = {
    Button: "button",
    Slider: "slider",
    CircularSlider: "circular_slider",
    Actions: "actions",
    ButtonsSlider: "buttons_slider",
    Switch: "switch"
}

# This is used for debug messaging and lines up with the layout_cells enum.
layoutNames = [
    "EMPTY",
    "OCCUPIED",
    "SQUARE",
    "VERTICAL_RECTANGLE",
    "HORIZONTAL_RECTANGLE",
    "BIG_SQUARE",
]


# we will be using a y,x coordinate system;
# so they will be looking at our grid left to right first,
# top to bottom after that.
class Grid:
    def __init__(self, command_name_generator, role=0, width=4, height=4):
        #self.grid = [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]]
        self.width = width
        self.height = height
        self.grid = []
        for y in range(self.height):
            self.grid.append([])
            for x in range(self.width):
                self.grid[y].append(0)
        print(f"INFO: Creating a new {self.width}x{self.height} grid.")
        self.objects = []
        self.command_name_generator = command_name_generator
        self.role = role
        self.level = 0

        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y][x] != layout_cells.EMPTY:
                    continue
                success = self.add_random_element(y, x)
                if success == False:
                    print("ERROR: No more words to use. Breaking out of tile creation.")
                    return # It means there are no more words to use.

    def add_random_element(self, y, x):

        # Default size is 1
        size = 1

        pool = [layout_cells.SQUARE]
        spaces_right = self.get_spaces_right(y, x)
        spaces_down = self.get_spaces_down(y, x)

        if spaces_right > 0:
            pool.append(layout_cells.HORIZONTAL_RECTANGLE)
        if spaces_down > 0:
            pool.append(layout_cells.VERTICAL_RECTANGLE)
        if (spaces_right > 0) and (spaces_down > 0):
            pool.append(layout_cells.BIG_SQUARE)

        # Select random block
        _type = random.choice(pool) if len(pool) != 0 else layout_cells.SQUARE

        # print(f"DEBUG: Placing {layoutNames[_type]} at {x}, {y}")
        

        if _type == layout_cells.HORIZONTAL_RECTANGLE or _type == layout_cells.BIG_SQUARE:
            if (self.level == 0):
                size = 2
            else: size = random.randint(2, self.width-1 - x)

        elif _type == layout_cells.VERTICAL_RECTANGLE:
            if (self.level == 0):
                size = 2
            else: size = random.randint(2, self.height-1 - y)

        # Add the block
        success = self.insert_object(y, x, _type, size)
        return success

    def insert_object(self, y, x, _type, size):

        self.grid[y][x] = _type

        if size != 1:
            if _type == layout_cells.VERTICAL_RECTANGLE:
                for i in range(y + 1, y + size):
                    self.grid[i][x] = layout_cells.OCCUPIED
            elif _type == layout_cells.HORIZONTAL_RECTANGLE:
                for i in range(x + 1, x + size):
                    self.grid[y][i] = layout_cells.OCCUPIED
            elif _type == layout_cells.BIG_SQUARE:
                self.grid[y + 1][x] = layout_cells.BIG_SQUARE
                self.grid[y][x + 1] = layout_cells.BIG_SQUARE
                self.grid[y + 1][x + 1] = layout_cells.BIG_SQUARE
                if size == 3:
                    for i in range(3):
                        self.grid[y + 2][x + i] = layout_cells.BIG_SQUARE
                    for i in range(3):
                        self.grid[y + i][x + 2] = layout_cells.BIG_SQUARE

        pool = []
        if _type in [layout_cells.SQUARE, layout_cells.BIG_SQUARE]:
            pool.append(Button)
            pool.append(Switch)
        if _type == layout_cells.VERTICAL_RECTANGLE and size == 2:
            for _ in range(2):
                pool.append(Actions)
        if _type in [layout_cells.VERTICAL_RECTANGLE, layout_cells.HORIZONTAL_RECTANGLE]:
            pool.append(Slider)
        if _type == layout_cells.BIG_SQUARE:
            for _ in range(3):
                pool.append(CircularSlider)
        if _type == layout_cells.HORIZONTAL_RECTANGLE:
            for _ in range(2):
                pool.append(ButtonsSlider)

        _object = random.choice(pool)

        init_kwargs = {
            "x": x,
            "y": y,
            "w": 1,
            "h": 1,
            "name": self.command_name_generator.generate_command_name(self.role)
        }

        if _type == layout_cells.VERTICAL_RECTANGLE:
            # Special size for vertical rectangle
            init_kwargs["w"] = 1
            init_kwargs["h"] = size
        elif _type == layout_cells.HORIZONTAL_RECTANGLE:
            # Special size for horizontal rectangle
            init_kwargs["w"] = size
            init_kwargs["h"] = 1
        elif _type == layout_cells.BIG_SQUARE:
            # Special size for big square rectangle
            init_kwargs["w"] = size
            init_kwargs["h"] = size

        if _object in [Slider, ButtonsSlider]:
            # Special kwargs for Sliders
            init_kwargs["min_value"] = 0
            init_kwargs["max_value"] = random.randint(3, 5)
        elif _object is CircularSlider:
            # Special kwargs for Sliders (different values)
            init_kwargs["min_value"] = 0
            init_kwargs["max_value"] = random.randint(4, 7)
        elif _object is Actions:
            # Special kwargs for Action
            init_kwargs["actions"] = [
                self.command_name_generator.generate_action() for _ in range(random.randint(2, 4))
            ]

        if init_kwargs["name"] == None:
            # The words list has run out of unique names to use,
            # so we should tell the grid to stop placing tiles.
            print("ERROR: Name was None, breaking tile generation.")
            return False
        cname = init_kwargs["name"]
        
        # Otherwise proceed as normal
        self.objects.append(_object(**init_kwargs))
        return True


    def get_spaces_right(self, y, x):
        count = 0
        for i in range(x+1, self.width):
            if self.grid[y][i] != layout_cells.EMPTY:
                return count
            count += 1
        return count

    def get_spaces_down(self, y, x):
        count = 0
        for i in range(y+1, self.height):
            if self.grid[i][x] != layout_cells.EMPTY:
                return count
            count += 1
        return count

    def jsonify(self):
        return json.dumps(self.objects, cls=GridJSONEncoder)

    def __dict__(self):
        result = []
        for i in self.objects:
            result.append(i.__dict__())
        return result

# if __name__ == "__main__":
#     print(Grid().jsonify())
