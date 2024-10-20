# tracker.py

import socket
import json
import sys
import threading
import logging
from common import User, Game
from typing import List, Dict

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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
        self.players: List[User] = []
        self.games: List[Game] = []
        self.game_id_counter = 0
        self.lock = threading.Lock()

    def handle_command(self, msg: dict, addr: tuple, sock: socket.socket):
        command = msg.get('command', '')
        method = getattr(self, f"cmd_{command}", None)
        if method:
            try:
                response = method(msg)
            except Exception as e:
                logging.error(f"Error processing command '{command}': {e}")
                response = {"status": "FAILURE", "message": f"Error processing command: {e}"}
        else:
            logging.warning(f"Unknown command received: {command}")
            response = {"status": "FAILURE", "message": "Unknown command"}
        sock.sendto(json.dumps(response).encode(), addr)

    def cmd_register(self, msg: dict) -> dict:
        try:
            return self.register_player(msg['player'], msg['IPv4'], msg['t-port'], msg['p-port'])
        except KeyError as e:
            logging.error(f"Missing key in register command: {e}")
            return {"status": "FAILURE", "message": f"Missing key: {e}"}

    def cmd_query_players(self, msg: dict) -> dict:
        return self.query_players()

    def cmd_start_game(self, msg: dict) -> dict:
        try:
            return self.start_game(msg['player'], msg['n'], msg['#holes'])
        except KeyError as e:
            logging.error(f"Missing key in start_game command: {e}")
            return {"status": "FAILURE", "message": f"Missing key: {e}"}

    def cmd_query_games(self, msg: dict) -> dict:
        return self.query_games()

    def cmd_end_game(self, msg: dict) -> dict:
        try:
            return self.end_game(msg['game-identifier'], msg['player'])
        except KeyError as e:
            logging.error(f"Missing key in end_game command: {e}")
            return {"status": "FAILURE", "message": f"Missing key: {e}"}

    def cmd_de_register(self, msg: dict) -> dict:
        try:
            return self.de_register(msg['player'])
        except KeyError as e:
            logging.error(f"Missing key in de_register command: {e}")
            return {"status": "FAILURE", "message": f"Missing key: {e}"}

    def register_player(self, username: str, ip: str, t_port: int, p_port: int) -> dict:
        with self.lock:
            if any(player.username == username for player in self.players):
                logging.warning(f"Duplicate username registration attempt: {username}")
                return {"status": "FAILURE", "message": "Duplicate username"}
            new_player = User(username, ip, t_port, p_port)
            self.players.append(new_player)
            logging.debug(f"Registered player: {new_player}")
            return {"status": "SUCCESS", "message": "Registered successfully"}

    def query_players(self) -> dict:
        with self.lock:
            return {
                "status": "SUCCESS",
                "count": len(self.players),
                "players": [player.to_dict() for player in self.players]
            }

    def start_game(self, dealer_name: str, n: int, holes: int) -> dict:
        with self.lock:
            dealer = next((p for p in self.players if p.username == dealer_name and p.state == "free"), None)
            if not dealer:
                logging.warning(f"Dealer not found or already in a game: {dealer_name}")
                return {"status": "FAILURE", "message": "Dealer not registered or already in a game"}
            if n < 1 or n > 3:
                logging.warning(f"Invalid number of players to start game: {n}")
                return {"status": "FAILURE", "message": "Invalid number of players"}
            available_players = [p for p in self.players if p.state == "free" and p.username != dealer_name]
            if len(available_players) < n:
                logging.warning("Not enough available players to start the game")
                return {"status": "FAILURE", "message": "Not enough available players"}
            players = [dealer] + available_players[:n]
            for player in players:
                player.state = "in-play"
            game = Game(dealer, players, self.game_id_counter, holes)
            self.games.append(game)
            self.game_id_counter += 1
            logging.debug(f"Started game {game.id} with players: {[p.username for p in players]} and holes: {holes}")

            # Notify all assigned players about the game assignment
            assigned_game_msg = {
                "command": "assigned_game",
                "game_id": game.id,
                "dealer": dealer.to_dict(),
                "players": [player.to_dict() for player in players],
                "holes": holes
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

    def send_message_to_player(self, msg: dict, player: User):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(msg).encode(), (player.ip, player.p_port))
            sock.close()
            logging.debug(f"Sent assigned_game message to {player.username} at {player.ip}:{player.p_port}")
        except Exception as e:
            logging.error(f"Failed to send assigned_game to {player.username}: {e}")

    def query_games(self) -> dict:
        with self.lock:
            return {
                "status": "SUCCESS",
                "count": len(self.games),
                "games": [game.to_dict() for game in self.games]
            }

    def end_game(self, game_id: int, dealer_name: str) -> dict:
        with self.lock:
            game = next((g for g in self.games if g.id == game_id and g.dealer.username == dealer_name), None)
            if not game:
                logging.warning(f"Game not found or dealer mismatch for game_id {game_id}, dealer {dealer_name}")
                return {"status": "FAILURE", "message": "Game not found or dealer mismatch"}
            for player in game.players:
                player.state = "free"
            self.games.remove(game)
            logging.debug(f"Ended game {game.id}")
            return {"status": "SUCCESS", "message": "Game ended successfully"}

    def de_register(self, username: str) -> dict:
        with self.lock:
            player = next((p for p in self.players if p.username == username), None)
            if not player:
                logging.warning(f"Attempt to deregister non-existent player: {username}")
                return {"status": "FAILURE", "message": "Player not found"}
            if player.state == "in-play":
                logging.warning(f"Attempt to deregister player in an ongoing game: {username}")
                return {"status": "FAILURE", "message": "Player is in an ongoing game"}
            self.players.remove(player)
            logging.debug(f"Deregistered player: {player.username}")
            return {"status": "SUCCESS", "message": "Deregistered successfully"}

def main():
    tracker = Tracker()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, PORT))
    except Exception as e:
        logging.error(f"Failed to bind to port {PORT}: {e}")
        sys.exit(1)
    logging.debug(f"Tracker listening on port {PORT}")
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            msg = json.loads(data.decode())
            threading.Thread(target=tracker.handle_command, args=(msg, addr, sock), daemon=True).start()
        except KeyboardInterrupt:
            logging.info("Shutting down the tracker.")
            break
        except Exception as e:
            logging.error(f"Error receiving data: {e}")
    sock.close()

if __name__ == "__main__":
    main()
