import asyncio
import logging
import random

from server import Client
from server.game_modifiers import FlipGrid, Symbols, BlackHolesField, AsteroidsField, Alien
from server.instruction import Instruction
from singletons.config import Config
from singletons.lobby_manager import LobbyManager
from singletons.sio import Sio
from utils.command_name_generator import CommandNameGenerator
from utils.grid import Grid, Button, SliderLikeElement, Actions, Switch, GridElement
from utils.special_commands import DummyAsteroidCommand, DummyBlackHoleCommand, SpecialCommand


class Slot:
    def __init__(self, client, ready=False, host=False, role=0):
        self.client = client
        self.ready = ready
        self.intro_done = False
        self.host = host
        self.role = role

        self.has_completed_special_action = False

        self.grid = None
        self.instruction = None
        self.next_generation_task = None

        self.defeating_asteroid = False
        self.defeating_black_hole = False

        self.special_command_cooldown = 0

    def sio_slot_info(self):
        return {
            "uid": self.client.uid,
            "ready": self.ready,
            "host": self.host
        }

    async def reset_asteroid(self, after=2):
        await asyncio.sleep(after)
        self.defeating_asteroid = False

    async def reset_black_hole(self, after=2):
        await asyncio.sleep(after)
        self.defeating_black_hole = False


class Game:
    STARTING_HEALTH = 50
    HEALTH_LOOP_RATE = 2
    MAX_PLAYERS = 4

    def __init__(self, name, public):
        self._uuid = None   # implemented as a property

        self.name = name

        self.public = public
        self.max_players = 2

        self.slots = []
        self.playing = False
        self.disposing = False
        self.instructions = []

        self.level = -1
        self.health = self.STARTING_HEALTH
        self.death_limit = 0

        self.health_drain_task = None

        self.previous_game_modifier = None
        self.game_modifier = None
        self.game_modifier_task = None
        self.special_action = None
        self.special_actions = []

        self.difficulty = {
            "instructions_time": 25,                        # seconds to complete an instruction
            "health_drain_rate": 0.5,                       # health drain per second
            "death_limit_increase_rate": 0.05,              # death barrier progress per second
            "completed_instruction_health_increase": 10,    # health increase per instruction completed
            # "useless_command_health_decrease": 0,         # health decrease per useless instruction (removed)
            "expired_command_health_decrease": 5,           # health decrease per instruction failed
            "asteroid_chance": 0,                           # chance of getting an asteroid (0.0 - 1.00)
            "black_hole_chance": 0,                         # chance of getting a black hole (0.0 - 1.00)
            "special_command_cooldown": 3,                  # instructions between special commands (asteroid and bh)
            "game_modifier_chance": 0.1                     # chance of getting a game modifier (0.0 - 1.00)
        }
        self.vanilla_difficulty = self.difficulty

    @property
    def uuid(self):
        """
        uuid property getter
        :return:
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """
        uuid setter. uuid can be set only one
        :param uuid:
        :return:
        """
        if self._uuid is not None:
            raise RuntimeError("Game's uuid cannot be changed!")
        self._uuid = uuid

    async def join_client(self, client):
        """
        Adds a client to the match and notifies match and lobby
        :param client: `Client` object
        :return:
        """
        if self.playing:
            raise RuntimeError("The game is in progress!")
        if type(client) is not Client:
            raise TypeError("`client` must be a Client object")
        # if client in self.clients:
        #     raise ValueError("This client is already in that lobby")

        # Make sure the room is not completely full
        if len(self.slots) >= self.max_players:
            await Sio().emit("game_join_fail", {
                "message": "The game is full"
            }, room=client.sid)
            return

        # Add the client to this match's clients
        self.slots.append(Slot(client, host=len(self.slots) == 0, role=min(len(self.slots), 3))) # !todo: parameterise max number of roles

        # Enter sio room
        Sio().enter_room(client.sid, self.sio_room)

        # Bind client to this game
        await client.join_game(self)

        # Notify joined client
        await Sio().emit("game_join_success", {
            "game_id": self.uuid
        }, room=client.sid)

        # Notify other clients (if this is not the first one joining aka the one creating the room)
        # await Sio().emit("client_joined", room=self.sio_room, skip_sid=client.sid)
        if len(self.slots) > 0:
            await self.notify_game()

        # Notify lobby if public
        await self.notify_lobby()

        logging.info("{} joined game {}".format(client.sid, self.uuid))

        if Config()["SINGLE_PLAYER"]:
            await self.start()

    async def remove_client(self, client):
        """
        Removes a client from the match and notifies game and lobby.
        If the host leaves, a new random host is chosen.
        If all players leave, the match is disposed.
        :param client: `Client` object to remove
        :return:
        """
        if type(client) is not Client:
            raise TypeError("`client` must be a Client object")
        # if client not in self.clients:
        #     raise ValueError("This client is not in that lobby")

        # Get client to remove
        slot_to_remove = None
        for c in self.slots:
            if c.client == client:
                slot_to_remove = c

        if slot_to_remove is None:
            raise ValueError("This client is not in that lobby")

        # Remove the client
        self.slots.remove(slot_to_remove)

        # Leave sio room
        Sio().leave_room(client.sid, self.sio_room)

        if self.playing and not self.disposing:
            # If we are in game, disconnect everyone
            try:
                await Sio().emit('player_disconnected', room=self.sio_room)
                await self.dispose()
            except RuntimeError:
                # Already disposing
                pass
        elif not self.playing:
            # Choose another host if host left
            if slot_to_remove.host and len(self.slots) > 0:
                new_host = random.choice(self.slots)
                new_host.host = True
                logging.info("{} chosen as new host in game {}".format(client.sid, self.uuid))

            # Notify other clients
            await self.notify_game()

            # Notify lobby
            await self.notify_lobby()

            # Dispose room if everyone left
            if self.is_empty:
                await self.dispose()

        logging.info("{} left game {}".format(client.sid, self.uuid))

    @property
    def sio_room(self):
        return "game/{}".format(self.uuid)

    @property
    def is_empty(self):
        return len(self.slots) == 0

    async def notify_lobby(self):
        if self.public:
            await Sio().emit("lobby_info", self.sio_lobby_info(), room="lobby")

    async def notify_game(self):
        await Sio().emit("game_info", self.sio_game_info(), room=self.sio_room)

    async def notify_lobby_dispose(self):
        await Sio().emit("lobby_disposed", {
            "game_id": self.uuid
        }, room="lobby")

    def sio_lobby_info(self):
        return {
            "name": self.name,
            "game_id": self.uuid,
            "players": len(self.slots),
            "max_players": self.max_players,
            "public": self.public
        }

    def sio_game_info(self):
        return {**self.sio_lobby_info(), **{
            "slots": [x.sio_slot_info() for x in self.slots] + [None] * (self.max_players - len(self.slots))
        }}

    def get_host(self):
        """
        Returns the `Slot` object of this match's host
        :return: `Slot` object or `None` if there's no host set
        """
        for x in self.slots:
            if x.host:
                return x
        return None

    def get_slot(self, client):
        """
        Get the `Slot` object corresponding to `Client`
        :param client:
        :return: `Slot` object or `None` if the client is not in this match
        """
        for x in self.slots:
            if x.client == client:
                return x
        return None

    async def update_settings(self, size=None, public=None):
        """
        Updates game settings and broadcasts events to game and lobby
        :param size: new size. min 2 max 4. Use `None` to leave untouched.
        :param public: new public status (True/False). Use `None` to leave untouched.
        :return:
        """
        if self.playing:
            raise RuntimeError("Game in progress!")
        visibility_changed = False
        if size is not None and 2 <= size <= self.MAX_PLAYERS:
            self.max_players = size
        if public is not None:
            self.public = public
            visibility_changed = True
        await self.notify_game()

        if self.public:
            # If the game is public, always send updated info to lobby
            await self.notify_lobby()
        elif visibility_changed:
            # Otherwise, if it has just changed to private,
            # make it disappear in lobbies list
            await self.notify_lobby_dispose()

    async def ready(self, client):
        """
        Toggles `client`'s ready status
        :param client: `Client` object
        :return:
        """
        if self.playing:
            raise RuntimeError("Game in progress!")
        slot = self.get_slot(client)
        if slot is None:
            raise ValueError("Client not in match")
        slot.ready = not slot.ready
        await self.notify_game()

    async def start(self):
        """
        Starts the game
        :return:
        """
        if len(self.slots) > 1 and all([x.ready for x in self.slots]) or Config()["SINGLE_PLAYER"]:
            # Game starts
            self.playing = True

            # Remove game from lobby
            await self.notify_lobby_dispose()

            # First level
            await self.next_level()

            # Notify all clients
            for slot in self.slots:
                print(f"Sending 'game_started' event to client: ${slot.client.sid}")
                await Sio().emit("game_started", {
                    "role": slot.role
                }, room=slot.client.sid)
        else:
            raise RuntimeError("Conditions not met for game to start")

    async def next_level(self):
        """
        Changes level, difficulty, resets intro done,
        sets game modifiera and generates new grids
        :return:
        """
        # Stop drain loop task
        if self.health_drain_task is not None:
            self.health_drain_task.cancel()

        # Stop game modifier task
        if self.game_modifier_task is not None:
            self.game_modifier_task.cancel()

        # Stop all command generation loop tasks
        for slot in self.slots:
            if slot.next_generation_task is not None:
                slot.next_generation_task.cancel()

        # Go to next level
        self.level += 1
        if (self.level == 0):
            print("INFO: Starting the game")
        else:
            print(f"INFO: Advancing to level {self.level+1}.")

        # Reset health and death limit
        self.health = self.STARTING_HEALTH
        self.death_limit = 0

        # Change difficulty settings if this is not the first level
        if self.level > 0:
            # Remove any eventual game modifier difficulty changes
            #logging.debug("VANILLA DIFF: {}".format(self.vanilla_difficulty))
            self.difficulty = self.vanilla_difficulty

            self.difficulty["instructions_time"] = max(7.0, self.difficulty["instructions_time"] - 1.25)
            self.difficulty["health_drain_rate"] = min(1.25, self.difficulty["health_drain_rate"] + 0.35)
            self.difficulty["death_limit_increase_rate"] = min(1.25, self.difficulty["death_limit_increase_rate"] + 0.15)
            self.difficulty["completed_instruction_health_increase"] = max(
                3.0,
                self.difficulty["completed_instruction_health_increase"] - 0.5
            )
            self.difficulty["expired_command_health_decrease"] = min(
                11.5,
                self.difficulty["expired_command_health_decrease"] + 0.25
            )

            self.difficulty["asteroid_chance"] = 0
            self.difficulty["black_hole_chance"] = 0

            # if self.level > 5:
            #     self.difficulty["useless_command_health_decrease"] = min(
            #         2.25,
            #         self.difficulty["useless_command_health_decrease"] + 0.1
            #     )
            self.difficulty["game_modifier_chance"] = min(1.0, self.difficulty["game_modifier_chance"] + 0.25)
            logging.debug("Current difficulty: {}".format(self.difficulty))

        # Set all `intro done` to false
        for i in self.slots:
            i.intro_done = False

        # Game modifier difficulty change
        #if self.game_modifier is not None:
        #    self.difficulty = self.game_modifier.difficulty_post_processor(self.difficulty)

        # Set size of grid
        self.gridSize = int(self.level/2+1) +1 # /2 +1 so that level 1 == 2x2 grid, level 2 == 2x2, level 3 == 3x3, etc.
        self.gridSize = min(self.gridSize, 4) # Clamp to maximum 4x4 grid size to prevent screen size issues.
        
        # Note: This could easily support uneven grids, just would need to specify on backend
        # here, and on client-side would need to specify at GameField.vue @ gridStyle.

        # Generate grids
        await self.generate_grids(self.gridSize, self.gridSize)

        # Start game modifier task if needed
        #if self.game_modifier is not None:
        #    self.game_modifier_task = asyncio.Task(self.game_modifier.task())

        # Game modifiers
        self.previous_game_modifier = self.game_modifier
        self.special_actions = ["Macy's Parade", "4th of July Fireworks", "Vote", "Bagel", "A Slice of Pizza"]
        rand_objects = {
            "Macy's Parade": Actions,
            "4th of July Fireworks": Actions,
            "Vote": Actions,
            "Bagel": Actions,
            "A Slice of Pizza": Actions
        }
        rand_actions = {
            "Macy's Parade": ["Attend"],
            "4th of July Fireworks": ["Watch"],
            "Vote": ["Submit"],
            "Bagel": ["Eat"],
            "A Slice of Pizza": ["Eat"]
        }
        print("[Game] Selecting game modifier...")
        if (len(self.special_actions) > 0):
            rand_object_name = random.choice(
                list(filter(
                    lambda x: x != self.previous_game_modifier, self.special_actions
                ))
            )
            self.game_modifier = rand_object_name
        else:
            rand_object_name = self.special_actions[0]
            
        print(f"[Game] Selected `{rand_object_name}`.")

        min_time = self.difficulty["instructions_time"]
        max_time_duration = min_time * 1
        #rand_time = min_time + (random.random() * max_time_duration)
        rand_time = 10 + (15 * random.random())
        for slot in self.slots:
            # Pick a random object to replace
            objects = slot.grid.objects
            index = random.randrange(0, len(objects)-1)
            old_object = objects[index]

            # Configure Button object
            new_object = rand_objects[rand_object_name](
                name=rand_object_name,
                x=old_object.x,
                y=old_object.y,
                w=old_object.w,
                h=old_object.h,
                actions=rand_actions[rand_object_name]
            )

            print(f"ind={index} x={new_object.x} y={new_object.y} w={new_object.w} h={new_object.h}")

            # Replace old with new
            slot.grid.objects[index] = new_object

            # Schedule instruction
            print(f"[Game] Scheduled special task for slot {slot.client.sid} in {rand_time} seconds.")
            slot.next_generation_task = asyncio.Task(self.schedule_generation(slot, rand_time, expired=None, stop_old_task=True, command=new_object))

    async def generate_grids(self, width, height):
        """
        Generates new `Grid`s for all clients
        :return:
        """
        if not self.playing:
            raise RuntimeError("Game not in progress!")
        name_generator = CommandNameGenerator()

        for slot in self.slots:
            g = Grid(name_generator, slot.role, width=width, height=height, level=self.level)

            # Game modifier post processor if needed
            #if self.game_modifier is not None:
            #    try:
            #        self.game_modifier.grid_post_processor(g)
            #    except NotImplementedError:
            #        pass

            slot.grid = g

    async def intro_done(self, client):
        """
        Sets that a client has played the intro.
        When everyone has played the intro, `self.intro_done_all()` is called
        :param client: `Client` object
        :return:
        """
        if not self.playing:
            raise RuntimeError("Game not in progress!")
        slot = self.get_slot(client)
        if slot is None:
            raise ValueError("Client not in match")

        # This client has played the intro
        slot.intro_done = True

        # Check if everyone has played the intro
        for i in self.slots:
            if not i.intro_done:
                return
        await self.intro_done_all()

    async def intro_done_all(self):
        """
        Called when all clients have played the intro.
        This emits to all clients their `grid` event and the first `command` event
        :return:
        """
        # Notify each client about their grid if eveyone has completed intro
        for slot in self.slots:
            await Sio().emit("grid", slot.grid.__dict__(), room=slot.client.sid)

        # Warmup dummy instruction
        warmup_time = max(int(self.difficulty["instructions_time"] / 5), 3)
        await Sio().emit("command", {
            "text": "Prepare to receive instructions",
            "time": warmup_time
        }, room=self.sio_room)

        # Wait until the dummy instruction expires
        await asyncio.sleep(warmup_time)

        # Generate first command for each slot, starting the regeneration loop as well
        for slot in self.slots:
            await self.generate_instruction(slot, stop_old_task=False)

        # Star the health drain task too
        self.health_drain_task = asyncio.Task(self.health_drain_loop())

    async def generate_instruction(self, slot, expired=None, stop_old_task=True, command=None):
        """
        Generates and sets a valid and unique Instruction for `Slot` and schedules
        an asyncio Task to run
        :param slot: `Slot` object that will be the target of that instruction
        :param stop_old_task: if `True`, stop the old generation task.
                              Set to `False` if running in the generation loop, `True` if calling from outside the loop.
        :param expired: Send this to the client with the new instruction.
                        If `True`, the old instruction expired.
                        If `False`, the old instruction was successful.
                        If `None` (or not present), not specified.
                        The client will play sounds and visual fx accordingly.
        :return:
        """
        # Stop the old next generation task if needed
        if slot.next_generation_task is not None and stop_old_task:
            slot.next_generation_task.cancel()
        old_instruction = slot.instruction

        #print(f"generate_instruction(slot={slot.client.sid}, expired={expired}, stop_old_task={stop_old_task}, command={command.name if command else command})")

        target = random.choice(list(filter(lambda z: z != slot, self.slots)))

        self.special_action = command.name if command else None

        # Choose between an asteroid/black hole or normal command
        if command is None:
            if random.random() < self.difficulty["asteroid_chance"] and slot.special_command_cooldown <= 0:
                # Asteroid, force target and command
                target = None
                command = DummyAsteroidCommand()
                slot.special_command_cooldown = self.difficulty["special_command_cooldown"] + 1
            elif random.random() < self.difficulty["black_hole_chance"] and slot.special_command_cooldown <= 0:
                # Black hole, force target and command
                target = None
                command = DummyBlackHoleCommand()
                slot.special_command_cooldown = self.difficulty["special_command_cooldown"] + 1
            elif Config()["SINGLE_PLAYER"]:
                # Single player debug mode, force target only
                target = slot
            else:
                # Normal, choose a target
                # Choose a random slot and a random command.
                # We don't do this in `Instruction` because we need to access
                # match's properties and passing match and next_levelinstruction to `Instruction` is not elegant imo
                if random.randint(0, 5) == 0:
                    # 1/5 chance of getting a command in our grid
                    target = slot
                else:
                    # Filter out our slot and chose another one randomly
                    target = random.choice(list(filter(lambda z: z != slot, self.slots)))

        # Decrease special command cooldown
        slot.special_command_cooldown = max(0, slot.special_command_cooldown - 1)
        logging.debug("SPECIAL {}".format(slot.special_command_cooldown))

        # Generate a command if needed
        if command is None:
            #print("Generating command...")
            # Find a random command that is not used in any other instructions at the moment
            # and is not the same as the previous one - unless there is only one instruction.
            found_valid_command = False
            for _ in target.grid.objects:
                if (found_valid_command): break

                # Pick a random instruction.
                options = []
                debug_names = []
                for object in target.grid.objects:
                    if object.name in self.special_actions:
                        continue
                    else:
                        options.append(object)
                        debug_names.append(object.name)

                command = random.choice(options)

                # Search current instructions to see if that was a valid command (i.e. not in use).
                found_valid_command = True
                currentInstructions = self.instructions # This may be None according to old documentation.
                if slot.instruction is not None: currentInstructions.append(slot.instruction)
                for _instruction in currentInstructions:
                    if (_instruction.target_command == command):
                        # We selected a dud instruction, pick another one.
                        found_valid_command = False
                        break

            if not found_valid_command:
                # It means the only available instructions are all in use.
                command = random.choice(options)

            #print(debug_names)
            print(f"Generated {command.name}")

        # Set this slot's instruction and notify the client
        slot.instruction = Instruction(slot, target, command, special_action=True if self.special_action else False)

        # Add new one
        self.instructions.append(slot.instruction)

        # Notify the client about the new command and the status of the old command
        await Sio().emit("command", {
            "text": slot.instruction.text,
            "time": self.difficulty["instructions_time"],
            "expired": expired,
        }, room=slot.client.sid)

        if old_instruction is not None and issubclass(type(old_instruction.target_command), SpecialCommand):
            await Sio().emit("safe", room=self.sio_room)

        # Schedule a new generation
        slot.next_generation_task = asyncio.Task(self.schedule_generation(slot, self.difficulty["instructions_time"]))

    async def schedule_generation(self, slot, seconds, expired=True, stop_old_task=False, command=None):
        """
        Executes a new instruction generation for `slot` after `seconds` have passed
        :param slot: `Slot` object that will receive the `Instruction`
        :param seconds: number of seconds to wait
        :return:
        """
        await asyncio.sleep(seconds)

        #print(f"schedule_generation(slot={slot.client.sid}, seconds={seconds}, expired={expired}, command={command.name if command else command})")

        # Remove expired instruction
        if slot.instruction in self.instructions:
            self.instructions.remove(slot.instruction)

        # Drain health
        self.health -= self.difficulty["expired_command_health_decrease"]

        # Generate a new instruction
        await self.generate_instruction(slot, expired=expired, stop_old_task=stop_old_task, command=command)

    async def health_drain_loop(self):
        while True:
            # Drain health every two seconds
            await asyncio.sleep(self.HEALTH_LOOP_RATE)
            self.health -= self.difficulty["health_drain_rate"] * self.HEALTH_LOOP_RATE
            self.death_limit = min(
                90,
                self.death_limit + self.difficulty["death_limit_increase_rate"] * self.HEALTH_LOOP_RATE
            )
            logging.debug("Draining health, new value {} and death limit is {}".format(self.health, self.death_limit))

            if self.health <= self.death_limit:
                # Game over
                print("INFO: Game over")
                await self.game_over()
                break
            else:
                # Game still in progress, broadcast new health
                await self.notify_health()

    async def game_over(self):
        await Sio().emit("game_over", {
            "level": self.level
        }, room=self.sio_room)
        logging.info("{} game over".format(self.uuid))

        # Reset stats
        self.level = -1
        self.health = self.STARTING_HEALTH
        self.death_limit = 0
        self.health_drain_task = None
        self.previous_game_modifier = None
        self.game_modifier = None
        self.game_modifier_task = None
        self.difficulty = self.vanilla_difficulty

    async def notify_health(self):
        await Sio().emit("health_info", {
            "health": self.health,
            "death_limit": self.death_limit
        }, room=self.sio_room)

    async def do_command(self, client, command_name, value=None):
        """
        Called when someone does something on a command on their grid
        :param client: `Client` object, must be in game
        :param command_name: changed command name, case insensitive
        :param value: command value, required only for slider-like, actions and switches commands
        :return:
        """
        # Playing/player checks
        if not self.playing:
            raise RuntimeError("Game not in progress!")
        slot = self.get_slot(client)
        if slot is None:
            raise ValueError("Client not in match")

        # Make sure the command is valid
        command = None
        for c in slot.grid.objects:
            if c.name == command_name:
                command = c
        if command is None:
            raise ValueError("Command not found")

        # Make sure value is valid
        if type(command) is Button and value is not None:
            raise ValueError("Invalid value, must be None")
        elif issubclass(type(command), SliderLikeElement) and type(value) is not int and (value < command.min or value > command.max):
            raise ValueError("Invalid value, must be an int between min and max")
        elif type(command) is Actions and type(value) is not str and value.lower() not in command.actions:
            raise ValueError("Invalid value, must be a valid action")
        elif type(command) is Switch and type(value) is not bool:
            raise ValueError("Invalid value, must be a bool")

        # Update status if it's a slider or switch
        if issubclass(type(command), SliderLikeElement):
            command.value = value
        elif type(command) is Switch:
            command.toggled = value

        # Check if this command completes an instruction
        instruction_completed = None
        for instruction in self.instructions:
            if issubclass(type(instruction.target_command), GridElement) \
                    and instruction.target_command.name == command_name and instruction.value == value \
                        and instruction.source.has_completed_special_action is False:
                instruction_completed = instruction

        if instruction_completed is None:
            # Useless command, apply penality
            # self.health -= self.difficulty["useless_command_health_decrease"]
            return

        # Complete this instruction and generate a new one
        await self.complete_instruction(instruction_completed)

    async def complete_instruction(self, instruction_completed, increase_health=True):

        if self.special_action is not None:
            all_completed = True
            #print("Checking for special actions...")
            for slot in self.slots:
                if slot is instruction_completed.source:
                    continue
                if slot.has_completed_special_action is False:
                    all_completed = False
                    break
            if all_completed:
                #print("special actions all completed")

                # Reset special actions
                for slot in self.slots:
                    slot.has_completed_special_action = False

                # Remove all instructions
                self.instructions = []

                # Increase health if needed
                if increase_health:
                    self.health += self.difficulty["completed_instruction_health_increase"]

                # Broadcast new health or next level
                if self.health >= 100:
                    await self.next_level()
                    await Sio().emit("next_level", {
                        "level": self.level,
                        #"modifier": self.game_modifier is not None,
                        #"text": self.game_modifier.DESCRIPTION if self.game_modifier is not None else "The public is happy - good job city management!"
                    }, room=self.sio_room)
                else:
                    # This was an useful command! Force new generation outside the loop
                    for slot in self.slots:
                        await self.generate_instruction(slot, expired=False, stop_old_task=True)
                    await self.notify_health()
            else:
                instruction_completed.source.has_completed_special_action = True
                print(f"Setting SID {instruction_completed.source.client.sid} to {instruction_completed.source.has_completed_special_action}")
                return

        # Remove old instruction
        self.instructions.remove(instruction_completed)

        # Increase health if needed
        if increase_health:
            self.health += self.difficulty["completed_instruction_health_increase"]

        # Broadcast new health or next level
        if self.health >= 100:
            await self.next_level()
            await Sio().emit("next_level", {
                "level": self.level,
                #"modifier": self.game_modifier is not None,
                #"text": self.game_modifier.DESCRIPTION if self.game_modifier is not None else "The public is happy - good job city management!"
            }, room=self.sio_room)
        else:
            # This was an useful command! Force new generation outside the loop
            await self.generate_instruction(instruction_completed.source, expired=False, stop_old_task=True)
            await self.notify_health()

    async def dispose(self):
        """
        Disposes the current room
        :return:
        """
        # Make sure the match is not already disposing
        if self.disposing:
            raise RuntimeError("The match is already disposing")
        self.disposing = True

        # Cancel all pending next generation tasks
        for slot in self.slots:
            if slot.next_generation_task is not None:
                logging.debug("slot {} generation task cancelled".format(slot))
                slot.next_generation_task.cancel()

        # Cancel health drain task too
        if self.health_drain_task is not None:
            logging.debug("Health drain task cancelled")
            self.health_drain_task.cancel()

        # Also game modifier task
        if self.game_modifier_task is not None:
            logging.debug("Game modifier task cancelled")
            self.game_modifier_task.cancel()

        # Make everyone leave the game
        for slot in self.slots:
            await slot.client.leave_game()

        # Remove from lobby
        await LobbyManager().remove_game(self)

        logging.info("{} match disposed".format(self.uuid))

    async def defeat_special(self, client, black_hole=False):
        # Playing/player checks
        if not self.playing:
            raise RuntimeError("Game not in progress!")
        slot = self.get_slot(client)
        if slot is None:
            raise ValueError("Client not in match")

        # Defeat thing
        if black_hole:
            slot.defeating_black_hole = True
        else:
            slot.defeating_asteroid = True

        # Check if everyone is defeating
        all_defeated = True
        for s in self.slots:
            if (not s.defeating_black_hole and black_hole) or (not s.defeating_asteroid and not black_hole):
                all_defeated = False
                break

        # Everyone has defeated asteroid/black hole!
        if all_defeated:
            logging.debug("All defeated!")

            # Check if there's a special command (we may have more than once)
            instructions_completed = []
            for instruction in self.instructions:
                if (type(instruction.target_command) is DummyBlackHoleCommand and black_hole) \
                        or (type(instruction.target_command) is DummyAsteroidCommand and not black_hole):
                    instructions_completed.append(instruction)

            # Complete all instructions (two loops because we're removing items from self.instructions)
            for instruction in instructions_completed:
                logging.debug("SPECIAL DONE!")
                await self.complete_instruction(instruction, increase_health=False)

        # Reset defeating back to False after two seconds
        asyncio.Task(slot.reset_black_hole() if black_hole else slot.reset_asteroid())



