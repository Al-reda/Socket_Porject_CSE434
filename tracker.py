# tracker.py

import socket
import json
import sys
import threading
from common import User, Game

if len(sys.argv) != 2:
    print("Usage: python tracker.py <port>")
    sys.exit(1)

HOST = ''
PORT = int(sys.argv[1])

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

    def handle_command(self, msg, addr, sock):
        command = msg.get('command', '')
        method = getattr(self, f"cmd_{command}", None)
        if method:
            try:
                response = method(msg)
            except Exception as e:
                response = {"status": "FAILURE", "message": f"Error processing command: {e}"}
        else:
            error_msg = {"status": "FAILURE", "message": "Unknown command"}
            response = error_msg
        sock.sendto(json.dumps(response).encode(), addr)

    def cmd_register(self, msg):
        return self.register_player(msg['player'], msg['IPv4'], msg['t-port'], msg['p-port'])

    def cmd_query_players(self, msg):
        return self.query_players()

    def cmd_start_game(self, msg):
        return self.start_game(msg['player'], msg['n'], msg['#holes'], msg.get('allow_steal', False))

    def cmd_query_games(self, msg):
        return self.query_games()

    def cmd_end(self, msg):
        return self.end_game(msg['game-identifier'], msg['player'])

    def cmd_de_register(self, msg):
        return self.de_register(msg['player'])

    def register_player(self, username, ip, t_port, p_port):
        with self.lock:
            if any(player.username == username for player in self.players):
                return {"status": "FAILURE", "message": "Duplicate username"}
            new_player = User(username, ip, t_port, p_port)
            self.players.append(new_player)
            print(f"DEBUG: Registered player: {new_player}")
            return {"status": "SUCCESS", "message": "Registered successfully"}

    def query_players(self):
        with self.lock:
            return {
                "status": "SUCCESS",
                "count": len(self.players),
                "players": [player.to_dict() for player in self.players]
            }

    def start_game(self, dealer_name, n, holes, allow_steal=False):
        with self.lock:
            dealer = next((p for p in self.players if p.username == dealer_name and p.state == "free"), None)
            if not dealer:
                return {"status": "FAILURE", "message": "Dealer not registered or already in a game"}
            try:
                n = int(n)
                holes = int(holes)
            except ValueError:
                return {"status": "FAILURE", "message": "Invalid number format for players or holes"}
            if n < 1 or n > 3:
                return {"status": "FAILURE", "message": "Invalid number of players"}
            available_players = [p for p in self.players if p.state == "free" and p.username != dealer_name]
            if len(available_players) < n:
                return {"status": "FAILURE", "message": "Not enough available players"}
            players = [dealer] + available_players[:n]
            for player in players:
                player.state = "in-play"
            game = Game(dealer, players, self.game_id_counter, holes)
            self.games.append(game)
            self.game_id_counter += 1
            print(f"DEBUG: Started game {game.id} with players: {[p.username for p in players]} and holes: {holes}")

            # Notify all assigned players about the game assignment
            assigned_game_msg = {
                "command": "assigned_game",
                "game_id": game.id,
                "dealer": dealer.to_dict(),
                "players": [player.to_dict() for player in players],
                "holes": holes,
                "allow_steal": allow_steal  # Include the steal option in the message
            }
            for player in players:
                self.send_message_to_player(assigned_game_msg, player)

            return {
                "status": "SUCCESS",
                "message": "Game started and players notified successfully",
                "game_id": game.id,
                "players": [player.to_dict() for player in players],
                "holes": holes
            }

    def send_message_to_player(self, msg, player):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(msg).encode(), (player.ip, player.p_port))
            sock.close()
            print(f"DEBUG: Sent assigned_game message to {player.username} at {player.ip}:{player.p_port}")
        except Exception as e:
            print(f"DEBUG: Failed to send assigned_game to {player.username}: {e}")

    def query_games(self):
        with self.lock:
            return {
                "status": "SUCCESS",
                "count": len(self.games),
                "games": [game.to_dict() for game in self.games]
            }

    def end_game(self, game_id, dealer_name):
        with self.lock:
            try:
                game_id = int(game_id)
            except ValueError:
                return {"status": "FAILURE", "message": "Invalid game identifier"}

            game = next((g for g in self.games if g.id == game_id and g.dealer.username == dealer_name), None)
            if not game:
                return {"status": "FAILURE", "message": "Game not found or dealer mismatch"}
            for player in game.players:
                player.state = "free"
            self.games.remove(game)
            print(f"DEBUG: Ended game {game.id}")
            return {"status": "SUCCESS", "message": "Game ended successfully"}

    def de_register(self, username):
        with self.lock:
            player = next((p for p in self.players if p.username == username), None)
            if not player:
                return {"status": "FAILURE", "message": "Player not found"}
            if player.state == "in-play":
                return {"status": "FAILURE", "message": "Player is in an ongoing game"}
            self.players.remove(player)
            print(f"DEBUG: Deregistered player: {player.username}")
            return {"status": "SUCCESS", "message": "Deregistered successfully"}

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
            msg = json.loads(data.decode())
            threading.Thread(target=tracker.handle_command, args=(msg, addr, sock), daemon=True).start()
        except KeyboardInterrupt:
            print("\nDEBUG: Shutting down the tracker.")
            break
        except Exception as e:
            print(f"DEBUG: Error receiving data: {e}")
    sock.close()

if __name__ == "__main__":
    main()