from utils.singleton import singleton


@singleton
class WordsStorage:
    def __init__(self):
        self.USE_PREFIXES = False
        self.USE_ADJECTIVES = False

        self.PREFIXES = [
            "MACRO" "MICRO",                                            # Size
            "MONO", "UNI", "BI", "TRI", "QUAD", "MULTI", "POLY"         # Quantity
            "ANTI", "CONTRA", "COM", "SYM",                             # Relationships
            "ANTE", "FORE", "PRE", "POST",                              # Position in time
            "CIRCUM", "EXO", "INTER", "INTRA", "PERI", "SUB", "TRANS",  # Position in space
            "EU", "MAL",                                                # Quality
            "DE", "DIS", "IN", "MIS", "NON", "UN"                       # Negation
        ]

        self.ROLE_0 = {
            "nouns": [],
            "adjectives": []
        }

        self.ROLE_1 = {
            "nouns": [],
            "adjectives": []
        }

        self.ROLE_2 = {
            "nouns": [],
            "adjectives": []
        }

        self.ROLE_3 = {
            "nouns": [],
            "adjectives": []
        }

        self.VERBS = []

    def load_nouns(self):
        lines = []
        with open("words/nouns.txt", "r") as f:
            lines += [x.lower().strip() for x in f.readlines()]

        for line in lines:
            parts = line.split(",")
            if len(parts) == 2:
                noun, role = parts
                if role == "0":
                    dest_list = self.ROLE_0["nouns"]
                elif role == "1":
                    dest_list = self.ROLE_1["nouns"]
                elif role == "2":
                    dest_list = self.ROLE_2["nouns"]
                elif role == "3":
                    dest_list = self.ROLE_3["nouns"]
                dest_list.append(noun)

            else:
                print(f"Warning: The word '{line}' in the NOUNS wordlist wasn't configured correctly! Ensure each entry has a comma followed by its role.")

    def load_adjectives(self):
        lines = []
        with open("words/adjectives.txt", "r") as f:
            lines += [x.lower().strip() for x in f.readlines()]

        for line in lines:
            parts = line.split(",")
            if len(parts) == 2:
                noun, role = parts
                if role == "0":
                    dest_list = self.ROLE_0["adjectives"]
                elif role == "1":
                    dest_list = self.ROLE_1["adjectives"]
                elif role == "2":
                    dest_list = self.ROLE_2["adjectives"]
                elif role == "3":
                    dest_list = self.ROLE_3["adjectives"]
                dest_list.append(noun)

            else:
                print(f"Warning: The word '{line}' in the ADJECTIVES wordlist wasn't configured correctly! Ensure each entry has a comma followed by its role.")

    def load_verbs(self):
        with open("words/verbs.txt", "r") as f:
            self.VERBS = [x.lower().strip() for x in f.readlines()]

    def load(self):
        self.load_nouns()
        self.load_adjectives()
        self.load_verbs()