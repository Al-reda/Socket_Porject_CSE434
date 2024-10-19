# tracker.py
import socket
import pickle
import sys
import threading
from common import User

if len(sys.argv) != 2:
    print("Usage: python tracker.py <port>")
    sys.exit(1)

HOST = ''
PORT = int(sys.argv[1])


class Tracker:
    def __init__(self):
        self.players = []
        self.lock = threading.Lock()

    def register_player(self, username, ip, t_port, p_port):
        with self.lock:
            for player in self.players:
                if player.username == username:
                    return "FAILURE: Duplicate username"
            new_player = User(username, ip, t_port, p_port)
            self.players.append(new_player)
            return "SUCCESS"

    def query_players(self):
        with self.lock:
            return len(self.players), self.players.copy()

    def query_games(self):
        with self.lock:
            # No games are managed in this milestone
            return 0, []

    def de_register(self, username):
        with self.lock:
            for player in self.players:
                if player.username == username:
                    self.players.remove(player)
                    return "SUCCESS"
            return "FAILURE: Player not found"


def handle_client(data, addr, tracker, sock):
    try:
        msg = pickle.loads(data)
        command = msg.get('command', '')
        # Log the message received from the client
        print(f"\n[Tracker] Received from {addr}: {msg}")

        if command == 'register':
            result = tracker.register_player(msg['player'], msg['IPv4'], msg['t-port'], msg['p-port'])
            # Log the response being sent
            print(f"[Tracker] Sending to {addr}: {result}")
            sock.sendto(result.encode(), addr)

        elif command == 'query_players':
            count, players = tracker.query_players()
            response = {
                'count': count,
                'players': players
            }
            # Log the response being sent
            print(f"[Tracker] Sending to {addr}: {response}")
            sock.sendto(pickle.dumps(response), addr)

        elif command == 'query_games':
            count, games = tracker.query_games()
            response = {
                'count': count,
                'games': games
            }
            # Log the response being sent
            print(f"[Tracker] Sending to {addr}: {response}")
            sock.sendto(pickle.dumps(response), addr)

        elif command == 'de_register':
            result = tracker.de_register(msg['player'])
            # Log the response being sent
            print(f"[Tracker] Sending to {addr}: {result}")
            sock.sendto(result.encode(), addr)

        else:
            error_msg = "FAILURE: Unknown command"
            # Log the response being sent
            print(f"[Tracker] Sending to {addr}: {error_msg}")
            sock.sendto(error_msg.encode(), addr)

    except Exception as e:
        print(f"[Tracker] Error with client {addr}: {e}")
        sock.sendto(b"FAILURE", addr)


def main():
    tracker = Tracker()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    print(f"Tracker listening on port {PORT}")

    while True:
        data, addr = sock.recvfrom(4096)
        threading.Thread(target=handle_client, args=(data, addr, tracker, sock)).start()


if __name__ == "__main__":
    main()