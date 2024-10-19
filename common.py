# common.py
class User:
    def __init__(self, username, ip, t_port, p_port):
        self.username = username
        self.ip = ip
        self.t_port = t_port
        self.p_port = p_port
        self.state = "free"

    def __repr__(self):
        return f"User(username={self.username}, ip={self.ip}, t_port={self.t_port}, p_port={self.p_port}, state={self.state})"