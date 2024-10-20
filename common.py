class User:
    def __init__(self, username, ip, t_port, p_port, state='free'):
        self.username = username
        self.ip = ip
        self.t_port = t_port
        self.p_port = p_port
        self.state = state

    def to_dict(self):
        return {
            'username': self.username,
            'ip': self.ip,
            't_port': self.t_port,
            'p_port': self.p_port,
            'state': self.state
        }

    def __repr__(self):
        return f"User({self.username}, {self.ip}, {self.t_port}, {self.p_port}, {self.state})"


class Game:
    def __init__(self, dealer, players, game_id, holes):
        self.dealer = dealer  # Instance of User
        self.players = players  # List of User instances
        self.id = game_id
        self.holes = holes

    def to_dict(self):
        return {
            'id': self.id,
            'dealer': self.dealer.to_dict(),
            'players': [player.to_dict() for player in self.players],
            'holes': self.holes
        }

    def __repr__(self):
        return f"Game({self.id}, {self.dealer.username}, {[p.username for p in self.players]}, {self.holes})"
