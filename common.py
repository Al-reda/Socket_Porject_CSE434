# common.py

from dataclasses import dataclass, field
from typing import List

@dataclass
class User:
    username: str
    ip: str
    t_port: int
    p_port: int
    state: str = field(default="free")  # Possible states: "free", "in-play"

    def __repr__(self):
        return (f"User(username={self.username}, ip={self.ip}, "
                f"t_port={self.t_port}, p_port={self.p_port}, state={self.state})")

@dataclass
class Game:
    dealer: User
    players: List[User]
    id: int
    holes: int

    def __repr__(self):
        player_names = ', '.join([player.username for player in self.players])
        return (f"Game(id={self.id}, dealer={self.dealer.username}, "
                f"players=[{player_names}], holes={self.holes})")