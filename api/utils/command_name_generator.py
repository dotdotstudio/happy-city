import random

from singletons.words_storage import WordsStorage


class CommandNameGenerator:
    def __init__(self, words_storage=None):
        if words_storage is None:
            words_storage = WordsStorage()
        self.words_storage = words_storage
        self.used_names = []
        self.used_verbs = []
        self.retry_limit = 100 # How many times will it look for a new word in the list before giving up?

    def random_noun(self, role=0):
        if role == 0:
            nouns = random.choice([self.words_storage.ROLE_0["nouns"]])
        elif role == 1:
            nouns = random.choice([self.words_storage.ROLE_1["nouns"]])
        elif role == 2:
            nouns = random.choice([self.words_storage.ROLE_2["nouns"]])
        elif role == 3:
            nouns = random.choice([self.words_storage.ROLE_3["nouns"]])
        noun = random.choice(nouns).lower()
        return noun

    def random_adjective(self, role=0):
        if role == 0:
            adjectives = random.choice([self.words_storage.ROLE_0["adjectives"]])
        elif role == 1:
            adjectives = random.choice([self.words_storage.ROLE_1["adjectives"]])
        elif role == 2:
            adjectives = random.choice([self.words_storage.ROLE_2["adjectives"]])
        elif role == 3:
            adjectives = random.choice([self.words_storage.ROLE_3["adjectives"]])
        adjective = random.choice(adjectives).lower()
        return adjective

    def generate_noun(self, role):
        i = 0
        while True:
            noun = self.random_noun(role)
            if (noun not in self.used_names):
                break
            if (i >= self.retry_limit):
                noun = None
                break
            i += 1

        if noun is None: return None
        return noun

    def generate_compound_noun(self, role):
        prefix = random.choice(self.words_storage.PREFIXES).lower()

        i = 0
        while True:
            noun = self.random_noun(role)
            if (noun not in self.used_names):
                break
            if (i >= self.retry_limit):
                noun = None
                break
            i += 1

        if noun is None: return None

        if prefix.endswith(noun[0]):
            prefix += "-"
        elif " " in noun:
            prefix += " "
        prefixNoun = f"{prefix}{noun}"
        return prefixNoun

    def generate_adjective_noun(self, role):
        i = 0
        while True:
            noun = self.random_noun(role)
            if (noun not in self.used_names):
                break
            if (i >= self.retry_limit):
                noun = None
                break
            i += 1

        i = 0
        while True:
            adjective = self.random_adjective(role)
            if (adjective not in self.used_names):
                break
            if (i >= self.retry_limit):
                adjective = None
                break
            i += 1

        if noun is None or adjective is None:
            return None

        adjectiveNoun = f"{adjective} {noun}"
        return adjectiveNoun

    def generate_command_name(self, role=0):
        generation_options = []

        # Basic nouns
        option_nouns = self.generate_noun(role)
        if option_nouns is not None:
            generation_options.append(option_nouns)

        # Compound nouns
        if self.words_storage.USE_PREFIXES == True:
            option_cnouns = self.generate_compound_noun(role)
            if option_cnouns is not None:
                generation_options.append(option_cnouns)

        # Descriptive nouns
        if self.words_storage.USE_ADJECTIVES == True:
            option_adjectives = self.generate_adjective_noun(role)
            if option_adjectives is not None:
                generation_options.append(option_adjectives)

        if len(generation_options) == 0:
            print("ERROR: No options left")
            return None

        cname = random.choice(generation_options)
        self.used_names.append(cname)
        return cname

    def generate_action(self):
        i = 0
        while True:
            verb = random.choice(self.words_storage.VERBS)
            if verb not in self.used_verbs:
                break
            if (i >= self.retry_limit):
                verb = None
                break
            i += 1
        if verb is not None: self.used_verbs.append(verb)
        return verb
