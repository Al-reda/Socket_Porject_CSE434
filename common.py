# common.py

from dataclasses import dataclass, field
from typing import List, Dict
import random

@dataclass
class User:
    username: str
    ip: str
    t_port: int
    p_port: int
    state: str = 'free'

    def to_dict(self) -> Dict:
        return {
            'username': self.username,
            'ip': self.ip,
            't_port': self.t_port,
            'p_port': self.p_port,
            'state': self.state
        }

@dataclass
class Game:
    dealer: User
    players: List[User]
    id: int
    holes: int

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'dealer': self.dealer.to_dict(),
            'players': [player.to_dict() for player in self.players],
            'holes': self.holes
        }

@dataclass(frozen=True)
class Card:
    value: str  # e.g., 'AS', '10D', 'KC'

    def __str__(self):
        return self.value

class Deck:
    def __init__(self):
        suits = ['C', 'D', 'H', 'S']
        values = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        self.cards: List[Card] = [Card(f"{v}{s}") for s in suits for v in values]
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

    def draw_card(self) -> Card:
        if not self.cards:
            raise ValueError("No more cards in the deck")
        return self.cards.pop()

    def add_cards(self, cards: List[Card]):
        self.cards.extend(cards)
        self.shuffle()
