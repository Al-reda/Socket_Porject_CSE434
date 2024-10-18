# tracker.py

import socket
import pickle
import sys
import threading
from common import User, Game

if len(sys.argv) != 2:
    print("Usage: python tracker.py <port>")
    sys.exit(1)

HOST = ''
PORT = int(sys.argv[1])  # Read port number from command line

# Validate port number (Example range: 1500-1999)
if not (1500 <= PORT <= 1999):
    print("Port number must be in the range 1500-1999")
    sys.exit(1)

class Tracker:
    def __init__(self):
        self.players = []
        self.games = []
        self.game_id_counter = 0
        self.lock = threading.Lock()

    def register_player(self, username, ip, t_port, p_port):
        with self.lock:
            for player in self.players:
                if player.username == username:
                    return "FAILURE: Duplicate username"
            new_player = User(username, ip, t_port, p_port)
            self.players.append(new_player)
            print(f"DEBUG: Registered player: {new_player}")
            return "SUCCESS: Registered successfully"

    def query_players(self):
        with self.lock:
            return len(self.players), self.players.copy()

    def start_game(self, dealer_name, n, holes):
        with self.lock:
            dealer = next((p for p in self.players if p.username == dealer_name and p.state == "free"), None)
            if not dealer:
                return "FAILURE: Dealer not registered or already in a game", None, None

            if n < 1 or n > 3:
                return "FAILURE: Invalid number of players", None, None

            available_players = [p for p in self.players if p.state == "free" and p.username != dealer_name]
            if len(available_players) < n:
                return "FAILURE: Not enough available players", None, None

            players = [dealer] + available_players[:n]
            for player in players:
                player.state = "in-play"

            game = Game(dealer, players, self.game_id_counter, holes)
            self.games.append(game)
            self.game_id_counter += 1

            # Debug print
            print(f"DEBUG: Started game {game.id} with players: {[p.username for p in players]} and holes: {holes}")

            return "SUCCESS", game.id, players

    def query_games(self):
        with self.lock:
            return len(self.games), self.games.copy()

    def end_game(self, game_id, dealer_name):
        with self.lock:
            game = next((g for g in self.games if g.id == game_id and g.dealer.username == dealer_name), None)
            if not game:
                return "FAILURE: Game not found or dealer mismatch"

            for player in game.players:
                player.state = "free"
            self.games.remove(game)
            print(f"DEBUG: Ended game {game.id}")
            return "SUCCESS: Game ended successfully"

    def de_register(self, username):
        with self.lock:
            player = next((p for p in self.players if p.username == username), None)
            if not player:
                return "FAILURE: Player not found"

            if player.state == "in-play":
                return "FAILURE: Player is in an ongoing game"

            self.players.remove(player)
            print(f"DEBUG: Deregistered player: {player.username}")
            return "SUCCESS: Deregistered successfully"

def handle_client(data, addr, tracker, sock):
    try:
        msg = pickle.loads(data)
        command = msg.get('command', '')

        if command == 'register':
            result = tracker.register_player(msg['player'], msg['IPv4'], msg['t-port'], msg['p-port'])
            sock.sendto(result.encode(), addr)

        elif command == 'query_players':
            count, players = tracker.query_players()
            response = {
                'count': count,
                'players': players
            }
            sock.sendto(pickle.dumps(response), addr)

        elif command == 'start_game':
            result, game_id, players = tracker.start_game(msg['player'], msg['n'], msg['#holes'])
            response = {
                'result': result,
                'game_id': game_id,
                'players': players
            }
            sock.sendto(pickle.dumps(response), addr)

        elif command == 'query_games':
            count, games = tracker.query_games()
            response = {
                'count': count,
                'games': games
            }
            sock.sendto(pickle.dumps(response), addr)

        elif command == 'end_game':
            result = tracker.end_game(msg['game-identifier'], msg['player'])
            sock.sendto(result.encode(), addr)

        elif command == 'de_register':
            result = tracker.de_register(msg['player'])
            sock.sendto(result.encode(), addr)

        else:
            error_msg = "FAILURE: Unknown command"
            sock.sendto(error_msg.encode(), addr)

    except Exception as e:
        print(f"DEBUG: Error handling client {addr}: {e}")
        error_msg = f"FAILURE: {str(e)}"
        sock.sendto(error_msg.encode(), addr)

def main():
    tracker = Tracker()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, PORT))
    except Exception as e:
        print(f"DEBUG: Failed to bind to port {PORT}: {e}")
        sys.exit(1)
    print(f"DEBUG: Tracker listening on port {PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(65535)
            threading.Thread(target=handle_client, args=(data, addr, tracker, sock), daemon=True).start()
        except KeyboardInterrupt:
            print("\nDEBUG: Shutting down the tracker.")
            break
        except Exception as e:
            print(f"DEBUG: Error receiving data: {e}")

    sock.close()

if __name__ == "__main__":
    main()