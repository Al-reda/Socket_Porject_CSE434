# player.py

import socket
import json
import threading
import sys
import random
import os
import time
import logging
from common import User, Game, Card, Deck
from typing import List, Dict

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

TRACE = True  # Enable detailed tracing for debugging

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

class Player:
    def __init__(self, tracker_ip: str, tracker_port: int, t_port: int, p_port: int, group_number: int):
        self.tracker_ip = tracker_ip
        self.tracker_port = tracker_port
        self.t_port = t_port
        self.p_port = p_port
        self.group_number = group_number
        self.name = None
        self.hand: List[Card] = []
        self.score = 0
        self.t_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.t_sock.bind(('', self.t_port))
            logging.debug(f"t_sock bound to port {self.t_port}")
        except OSError as e:
            logging.error(f"Error binding t_port {self.t_port}: {e}")
            sys.exit(1)
        self.p_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.p_sock.bind(('', self.p_port))
            logging.debug(f"p_sock bound to port {self.p_port}")
        except OSError as e:
            logging.error(f"Error binding p_port {self.p_port}: {e}")
            sys.exit(1)
        self.players_info: List[User] = []
        self.game_id = None
        self.holes = 0
        self.is_dealer = False
        self.stock_pile: List[Card] = []
        self.discard_pile: List[Card] = []
        self.hand_grid: List[List[Card]] = []
        self.card_statuses: List[List[bool]] = []
        self.current_player_index = 0
        self.game_over = False
        self.lock = threading.Lock()
        self.dealer_info: User = None
        self.scores: Dict[str, int] = {}
        self.running = True
        self.players_done: set = set()
        self.in_game = False

        # Flags and data for thread communication
        self.is_my_turn = False
        self.turn_data = {}
        self.steal_event = threading.Event()
        self.steal_response = {}
        self.steal_lock = threading.Lock()

        # Initialize turn_event for synchronization
        self.turn_event = threading.Event()

        # Calculate the port range based on the group number
        base_port = ((self.group_number - 1) // 2) * 1000 + (1000 if self.group_number % 2 == 0 else 1500)
        self.port_min = base_port
        self.port_max = base_port + 499

        if not (self.port_min <= self.t_port <= self.port_max) or not (self.port_min <= self.p_port <= self.port_max):
            logging.error(f"Port numbers must be in the range {self.port_min}-{self.port_max} for group {self.group_number}")
            sys.exit(1)

    def trace(self, message: str):
        if TRACE:
            logging.debug(f"[TRACE] {message}")

    def get_local_ip(self) -> str:
        """Retrieve the local IP address of the machine."""
        try:
            # Connect to a public DNS server to get the local IP address
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            logging.error(f"Error obtaining local IP: {e}")
            return "127.0.0.1"  # Fallback to localhost

    def send_message(self, msg: dict, ip: str, port: int, expect_response: bool = False, timeout: int = 5) -> dict:
        self.trace(f"Sending to {ip}:{port}: {msg}")
        try:
            sock = self.t_sock if port == self.tracker_port else self.p_sock
            sock.sendto(json.dumps(msg).encode(), (ip, port))
            if expect_response:
                sock.settimeout(timeout)
                data, _ = sock.recvfrom(65535)
                self.trace(f"Received from {ip}:{port}: {data}")
                return json.loads(data.decode())
        except socket.timeout:
            logging.warning("No response from server. Please try again later.")
        except Exception as e:
            logging.error(f"Error communicating with {ip}:{port}: {e}")
        finally:
            sock.settimeout(None)
        return {}

    def send_to_tracker(self, msg: dict) -> dict:
        return self.send_message(msg, self.tracker_ip, self.tracker_port, expect_response=True)

    def register(self):
        if self.name:
            print("You are already registered.")
            return
        self.name = input("Enter your username: ").strip()
        if not self.name:
            print("Username cannot be empty.")
            self.name = None
            return
        local_ip = self.get_local_ip()
        msg = {
            'command': 'register',
            'player': self.name,
            'IPv4': local_ip,
            't-port': self.t_port,
            'p-port': self.p_port
        }
        response = self.send_to_tracker(msg)
        if not response:
            self.name = None
            return
        print(response.get('message', ''))
        if response.get('status') != "SUCCESS":
            self.name = None

    def de_register(self):
        if not self.name:
            print("You are not registered.")
            return
        msg = {'command': 'de_register', 'player': self.name}
        response = self.send_to_tracker(msg)
        if response:
            print(response.get('message', ''))
            if response.get('status') == "SUCCESS":
                self.name = None

    def query_players(self):
        msg = {'command': 'query_players'}
        response = self.send_to_tracker(msg)
        if response and response.get('status') == 'SUCCESS':
            players = response.get('players', [])
            self.display_players(players)
        else:
            print("Failed to query players.")

    def query_games(self):
        msg = {'command': 'query_games'}
        response = self.send_to_tracker(msg)
        if response and response.get('status') == 'SUCCESS':
            games = response.get('games', [])
            self.display_games(games)
        else:
            print("Failed to query games.")

    def display_players(self, players: List[dict]):
        clear_screen()
        print(f"=== Player List ({len(players)} players) ===")
        print(f"{'Username':<15}{'IP':<15}{'T-Port':<10}{'P-Port':<10}{'State':<10}")
        print("-" * 60)
        for player in players:
            print(f"{player['username']:<15}{player['ip']:<15}{player['t_port']:<10}{player['p_port']:<10}{player['state']:<10}")
        print("-" * 60)

    def display_games(self, games: List[dict]):
        clear_screen()
        print(f"=== Game List ({len(games)} games) ===")
        for game in games:
            players = ', '.join([p['username'] for p in game['players']])
            print(f"Game ID: {game['id']} | Dealer: {game['dealer']['username']} | Players: {players} | Holes: {game['holes']}")
        if not games:
            print("No active games.")
        print("-" * 60)

    def start_game(self):
        if not self.name:
            print("You must register first.")
            return
        n = self.get_numeric_input("Enter number of additional players (1-3): ", 1, 3)
        if n is None:
            return
        holes = self.get_numeric_input("Enter number of holes (1-9): ", 1, 9)
        if holes is None:
            return
        msg = {'command': 'start_game', 'player': self.name, 'n': n, '#holes': holes}
        response = self.send_to_tracker(msg)
        if response and response.get('status') == 'SUCCESS':
            # No need to handle setup here; players will be notified automatically
            print("Game started successfully. Players have been notified.")
        else:
            print(f"Failed to start game: {response.get('message', '') if response else ''}")

    # Removed join_game method and related functionalities

    def setup_game(self, response: dict):
        self.game_id = response.get('game_id')
        self.players_info = [User(**player) for player in response.get('players', [])]
        self.holes = response.get('holes', 0)
        self.is_dealer = True
        self.dealer_info = next((p for p in self.players_info if p.username == self.name), None)
        self.score = 0
        self.scores = {player.username: 0 for player in self.players_info}
        print(f"\nGame {self.game_id} started with players: {[p.username for p in self.players_info]}")
        self.start_listening()
        self.in_game = True
        threading.Thread(target=self.play_game, daemon=True).start()

    # Removed setup_joined_game method

    def handle_assigned_game(self, msg: dict, addr):
        logging.debug("Received 'assigned_game' message.")
        game_id = msg.get('game_id')
        dealer_info = msg.get('dealer')
        players = msg.get('players', [])
        holes = msg.get('holes', 0)

        logging.debug(f"Validating 'assigned_game' message fields:")
        logging.debug(f"game_id: {game_id}")
        logging.debug(f"dealer_info: {dealer_info}")
        logging.debug(f"players: {players}")
        logging.debug(f"holes: {holes}")

        if game_id is None:
            self.trace("Invalid assigned_game message: 'game_id' is missing.")
            return
        if dealer_info is None:
            self.trace("Invalid assigned_game message: 'dealer' info is missing.")
            return
        if not players:
            self.trace("Invalid assigned_game message: 'players' list is empty.")
            return
        if holes <= 0:
            self.trace("Invalid assigned_game message: 'holes' must be greater than 0.")
            return

        with self.lock:
            self.game_id = game_id
            self.holes = holes
            self.players_info = [User(**player) for player in players]
            self.dealer_info = User(**dealer_info) if dealer_info else None
            self.is_dealer = (self.name == self.dealer_info.username)
            self.scores = {player.username: 0 for player in self.players_info}
            self.score = 0
            self.players_done = set()
            self.game_over = False
            self.in_game = True

        print(f"\n=== Assigned to Game {self.game_id} ===")
        print(f"Dealer: {self.dealer_info.username}")
        print(f"Players: {[player.username for player in self.players_info]}")
        print(f"Holes: {self.holes}")

        if self.is_dealer:
            threading.Thread(target=self.play_game, daemon=True).start()
        else:
            print("Waiting for the dealer to distribute hands...")

    def handle_send_hand(self, msg: dict, addr):
        logging.debug("Handling 'send_hand' message.")
        received_hand = msg.get('hand', [])
        dealer_info = msg.get('dealer_info')
        if isinstance(received_hand, list):
            self.hand = [Card(val) for val in received_hand]
            self.initialize_hand()
        else:
            self.trace("Invalid hand data received.")
        if dealer_info:
            self.dealer_info = User(**dealer_info)
            print(f"Dealer is {self.dealer_info.username}")
        else:
            print("Failed to receive dealer information.")

    def handle_your_turn(self, msg: dict, addr):
        logging.debug("Handling 'your_turn' message.")
        with self.lock:
            self.stock_pile = [Card(val) for val in msg.get('stock_pile', [])]
            self.discard_pile = [Card(val) for val in msg.get('discard_pile', [])]
            self.current_player_index = msg.get('current_player_index', 0)
            self.is_my_turn = True
            self.turn_data = msg
        self.trace("Updated stock_pile and discard_pile for turn.")

    def handle_update_piles(self, msg: dict, addr):
        logging.debug("Handling 'update_piles' message.")
        with self.lock:
            self.stock_pile = [Card(val) for val in msg.get('stock_pile', [])]
            self.discard_pile = [Card(val) for val in msg.get('discard_pile', [])]
        self.print_hand()

    def handle_end_game(self, msg: dict, addr):
        logging.debug("Handling 'end_game' message.")
        self.game_over = True
        self.in_game = False
        print("\nGame ended!")
        self.print_full_hand()  # Reveal all cards
        self.calculate_score()  # Calculate score based on all cards
        # Receive the scores from the dealer
        if 'scores' in msg:
            self.scores = msg['scores']
            winner = msg.get('winner', '')
            self.display_final_scores(winner)
        else:
            self.scores = {self.name: self.score}
            self.display_final_scores()

    def handle_update_player_state(self, msg: dict, addr):
        logging.debug("Handling 'update_player_state' message.")
        with self.lock:
            self.current_player_index = msg.get('current_player_index', 0)
            players = msg.get('players', [])
            if players:
                self.players_info = [User(**player) for player in players]
        self.trace(f"Updated current_player_index to {self.current_player_index}")

    def handle_turn_over(self, msg: dict, addr):
        logging.debug("Handling 'turn_over' message.")
        if self.is_dealer:
            self.turn_event.set()
            self.trace("Turn event set by 'turn_over'.")
        else:
            self.trace(f"Received turn_over from {addr}, but not the dealer.")

    def handle_steal_card(self, msg: dict, addr):
        logging.debug("Handling 'steal_card' message.")
        from_player = msg.get('from_player')
        face_up_cards = [(i, j) for i in range(2) for j in range(3) if self.card_statuses[i][j]]
        if not face_up_cards:
            response = {'command': 'steal_response', 'card': None}
        else:
            i, j = random.choice(face_up_cards)
            stolen_card = self.hand_grid[i][j]
            self.card_statuses[i][j] = False
            response = {'command': 'steal_response', 'card': stolen_card.value}
            print(f"{from_player} stole your {stolen_card}")
            self.print_hand()
        self.send_message(response, addr[0], addr[1])

    def handle_steal_response(self, msg: dict, addr):
        logging.debug("Handling 'steal_response' message.")
        with self.steal_lock:
            self.steal_response = msg
            self.steal_event.set()

    def handle_send_score(self, msg: dict, addr):
        logging.debug("Handling 'send_score' message.")
        self.send_score(addr)

    def handle_score_response(self, msg: dict, addr):
        logging.debug("Handling 'score_response' message.")
        player_name = msg.get('player')
        player_score = msg.get('score', 0)
        with self.lock:
            self.scores[player_name] = player_score
            if len(self.scores) == len(self.players_info):
                self.declare_winner()

    def handle_player_done(self, msg: dict, addr):
        logging.debug("Handling 'player_done' message.")
        player_name = msg.get('player')
        with self.lock:
            self.players_done.add(player_name)
            if self.is_dealer and self.check_game_end():
                self.game_over = True
                self.in_game = False
                self.end_game(self.game_id)

    def listen_for_player_messages(self):
        logging.debug("Listening for player messages...")
        while not self.game_over and self.running:
            try:
                data, addr = self.p_sock.recvfrom(65535)
                msg = json.loads(data.decode())
                command = msg.get('command', '')
                logging.debug(f"Received message from {addr}: {msg}")
                handler = getattr(self, f"handle_{command}", None)
                if handler:
                    handler(msg, addr)
                else:
                    logging.warning(f"Unknown command received: {command}")
            except Exception as e:
                logging.error(f"Error in listen_for_player_messages: {e}")

    def start_listening(self):
        if not hasattr(self, 'listener_thread') or not self.listener_thread.is_alive():
            self.listener_thread = threading.Thread(target=self.listen_for_player_messages, daemon=True)
            self.listener_thread.start()
            logging.debug("Listener thread started.")

    def get_numeric_input(self, prompt: str, min_value: int, max_value: int) -> int:
        while True:
            try:
                value = int(input(prompt))
                if min_value <= value <= max_value:
                    return value
                else:
                    print(f"Value must be between {min_value} and {max_value}.")
            except ValueError:
                print("Invalid input. Please enter a number.")

    def play_game(self):
        if self.is_dealer:
            logging.debug("Dealer is setting up the game.")
            deck = Deck()
            self.stock_pile = deck.cards.copy()
            hands = {}
            for player in self.players_info:
                hand = [self.stock_pile.pop() for _ in range(6)]
                hands[player.username] = hand
            # Send hands and dealer info to all players
            for player in self.players_info:
                if player.username != self.name:
                    self.send_hand(player, hands[player.username])
                else:
                    self.hand = hands[player.username]
                    self.initialize_hand()
            top_card = self.stock_pile.pop()
            self.discard_pile.append(top_card)
            print(f"Initial discard pile top card: {top_card}")
            self.current_player_index = 0
            # Start the turn management in a separate thread
            threading.Thread(target=self.manage_turns, daemon=True).start()
        else:
            # Non-dealer players just wait; their turns will be handled in the main loop
            pass

    def send_hand(self, player: User, hand: List[Card]):
        msg = {
            'command': 'send_hand',
            'hand': [card.value for card in hand],
            'dealer_info': self.dealer_info.to_dict()
        }
        self.send_message(msg, player.ip, player.p_port)
        logging.debug(f"Sent hand to {player.username}.")

    def initialize_hand(self):
        self.hand_grid = [self.hand[:3], self.hand[3:]]
        self.card_statuses = [[False]*3 for _ in range(2)]
        indices = [(i, j) for i in range(2) for j in range(3)]
        random_indices = random.sample(indices, 2)
        for i, j in random_indices:
            self.card_statuses[i][j] = True
        self.print_hand()

    def print_hand(self):
        clear_screen()
        print(f"\n=== {self.name}'s Hand ===")
        for row in range(2):
            row_display = ""
            for col in range(3):
                if self.card_statuses[row][col]:
                    card = self.hand_grid[row][col]
                    row_display += f"{card.value:<4} "
                else:
                    row_display += "***  "
            print(row_display)
        print("\nDiscard Pile Top Card:", self.discard_pile[-1] if self.discard_pile else "Empty")
        print("="*30)

    def print_full_hand(self):
        """Print the hand with all cards revealed."""
        clear_screen()
        print(f"\n=== {self.name}'s Final Hand ===")
        for row in range(2):
            row_display = ""
            for col in range(3):
                card = self.hand_grid[row][col]
                row_display += f"{card.value:<4} "
            print(row_display)
        print("="*30)

    def manage_turns(self):
        logging.debug("Managing turns.")
        self.scores = {player.username: 0 for player in self.players_info}
        while not self.game_over and self.running:
            current_player = self.players_info[self.current_player_index]
            print(f"\nIt's {current_player.username}'s turn.")
            if current_player.username == self.name:
                with self.lock:
                    self.is_my_turn = True
            else:
                msg = {
                    'command': 'your_turn',
                    'stock_pile': [card.value for card in self.stock_pile],
                    'discard_pile': [card.value for card in self.discard_pile],
                    'current_player_index': self.current_player_index
                }
                self.send_message(msg, current_player.ip, current_player.p_port)
                logging.debug(f"Sent 'your_turn' message to {current_player.username}.")

            self.turn_event.wait()
            self.turn_event.clear()
            if self.check_game_end():
                self.game_over = True
                self.in_game = False
                self.end_game(self.game_id)
                break
            with self.lock:
                self.current_player_index = (self.current_player_index + 1) % len(self.players_info)
            self.update_player_state()

    def play_turn(self):
        logging.debug("play_turn() invoked.")
        self.print_hand()
        print(f"\n=== {self.name}'s Turn ===")
        print(f"Discard Pile Top Card: {self.discard_pile[-1]}")
        print("\nChoose an action:")
        print("1. Draw from Stock")
        print("2. Draw from Discard")
        print("3. Steal a Card")
        while True:
            choice = input("Enter your choice (1-3): ").strip()
            if choice in ['1', '2', '3']:
                break
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")
        if choice == '1':
            self.draw_from_stock()
        elif choice == '2':
            self.draw_from_discard()
        elif choice == '3':
            self.steal_card()
        logging.debug("play_turn() completed.")

    def draw_from_stock(self):
        with self.lock:
            if not self.stock_pile:
                if len(self.discard_pile) > 1:
                    self.stock_pile = [Card(val) for val in self.discard_pile[:-1]]
                    self.discard_pile = [self.discard_pile[-1]]
                    random.shuffle(self.stock_pile)
                    print("DEBUG: Re-shuffled discard pile into stock pile.")
                else:
                    print("No cards left to draw.")
                    self.end_turn()
                    return
            drawn_card = self.stock_pile.pop()
        print(f"You drew {drawn_card}")
        self.handle_drawn_card(drawn_card)

    def draw_from_discard(self):
        with self.lock:
            if not self.discard_pile:
                print("Discard pile is empty.")
                self.end_turn()
                return
            drawn_card = self.discard_pile.pop()
        print(f"You picked up {drawn_card} from discard pile")
        self.handle_drawn_card(drawn_card)

    def handle_drawn_card(self, drawn_card: Card):
        while True:
            action = input("Do you want to (1) Swap or (2) Discard? ").strip()
            if action == '1':
                try:
                    row = int(input("Select row (0 or 1): "))
                    col = int(input("Select column (0, 1, or 2): "))
                    if not (0 <= row < 2 and 0 <= col < 3):
                        print("Invalid row or column.")
                        continue
                    discarded_card = self.hand_grid[row][col]
                    self.hand_grid[row][col] = drawn_card
                    self.card_statuses[row][col] = True
                    with self.lock:
                        self.discard_pile.append(discarded_card)
                    print(f"Swapped {discarded_card} with {drawn_card}")
                    break
                except ValueError:
                    print("Invalid input.")
            elif action == '2':
                with self.lock:
                    self.discard_pile.append(drawn_card)
                print(f"Discarded {drawn_card}")
                break
            else:
                print("Invalid action. Please choose again.")
        self.print_hand()
        self.update_piles()
        if self.is_all_cards_face_up():
            if self.is_dealer:
                with self.lock:
                    self.players_done.add(self.name)
                if self.check_game_end():
                    self.game_over = True
                    self.in_game = False
                    self.end_game(self.game_id)
            else:
                self.notify_dealer_player_done()
        self.end_turn()

    def is_all_cards_face_up(self) -> bool:
        return all([status for row in self.card_statuses for status in row])

    def notify_dealer_player_done(self):
        if not self.is_dealer:
            msg = {'command': 'player_done', 'player': self.name}
            self.send_message(msg, self.dealer_info.ip, self.dealer_info.p_port)
            logging.debug(f"Notified dealer {self.dealer_info.username} that you are done.")

    def steal_card(self):
        print("\nPlayers you can steal from:")
        with self.lock:
            stealable_players = [p for p in self.players_info if p.username != self.name]
        if not stealable_players:
            print("No players available to steal from.")
            self.end_turn()
            return
        for idx, player in enumerate(stealable_players):
            print(f"{idx + 1}. {player.username}")
        try:
            target_idx = int(input("Enter the number of the player to steal from: ")) - 1
            if not (0 <= target_idx < len(stealable_players)):
                print("Invalid player selected. Turn skipped.")
                self.end_turn()
                return
            target_player = stealable_players[target_idx]
        except ValueError:
            print("Invalid input. Turn skipped.")
            self.end_turn()
            return
        msg = {'command': 'steal_card', 'from_player': self.name}
        self.send_message(msg, target_player.ip, target_player.p_port)
        logging.debug(f"Sent 'steal_card' message to {target_player.username}.")
        self.steal_event = threading.Event()
        if self.steal_event.wait(timeout=10):  # Wait for steal response
            with self.steal_lock:
                response = self.steal_response
            if response.get('card') is None:
                print(f"{target_player.username} has no face-up cards to steal. Turn skipped.")
                self.end_turn()
            else:
                stolen_card = Card(response.get('card'))
                print(f"Stole card {stolen_card} from {target_player.username}")
                self.handle_drawn_card(stolen_card)
        else:
            print("No response from the target player. Turn skipped.")
            self.end_turn()

    def end_turn(self):
        if self.is_dealer:
            self.turn_event.set()
            logging.debug("Dealer has ended their turn.")
        else:
            msg = {'command': 'turn_over'}
            self.send_message(msg, self.dealer_info.ip, self.dealer_info.p_port)
            logging.debug("Notified dealer that your turn is over.")

    def update_piles(self):
        msg = {
            'command': 'update_piles',
            'stock_pile': [card.value for card in self.stock_pile],
            'discard_pile': [card.value for card in self.discard_pile]
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(msg, player.ip, player.p_port)
                    logging.debug(f"Sent 'update_piles' message to {player.username}.")

    def update_player_state(self):
        msg = {
            'command': 'update_player_state',
            'current_player_index': self.current_player_index,
            'players': [player.to_dict() for player in self.players_info]
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(msg, player.ip, player.p_port)
                    logging.debug(f"Sent 'update_player_state' message to {player.username}.")

    def check_game_end(self) -> bool:
        with self.lock:
            return len(self.players_done) >= 1  # Game ends when any player is done

    def end_game(self, game_id: int):
        self.calculate_score()
        print(f"\nFinal score for {self.name}: {self.score}")
        if self.is_dealer:
            with self.lock:
                self.scores[self.name] = self.score
            for player in self.players_info:
                if player.username != self.name:
                    msg = {'command': 'send_score'}
                    self.send_message(msg, player.ip, player.p_port)
                    logging.debug(f"Sent 'send_score' message to {player.username}.")
        else:
            self.send_score((self.dealer_info.ip, self.dealer_info.p_port))
        self.game_over = True
        self.in_game = False

    def send_score(self, addr: tuple):
        msg = {'command': 'score_response', 'player': self.name, 'score': self.score}
        self.send_message(msg, addr[0], addr[1])
        logging.debug(f"Sent 'score_response' message to dealer.")

    def declare_winner(self):
        winner = min(self.scores, key=self.scores.get)
        print("\n=== Final Scores ===")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        print(f"\nThe winner is {winner}!")
        end_game_msg = {
            'command': 'end_game',
            'scores': self.scores,
            'winner': winner
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(end_game_msg, player.ip, player.p_port)
                    logging.debug(f"Sent 'end_game' message to {player.username}.")
        msg = {'command': 'end_game', 'game-identifier': self.game_id, 'player': self.name}
        response = self.send_to_tracker(msg)
        if response:
            print(response.get('message', ''))
        self.game_over = True
        self.in_game = False

    def calculate_score(self):
        total = 0
        for col in range(3):
            column_cards = [self.hand_grid[row][col] for row in range(2)]
            # Check for pairs in the same column
            if column_cards[0].value[:-1] == column_cards[1].value[:-1]:
                continue  # Score for this column is zero
            for row in range(2):
                card_value = self.card_value(self.hand_grid[row][col].value)
                total += card_value
        self.score = total

    def card_value(self, card_str: str) -> int:
        value_str = card_str[:-1]
        if value_str == 'A':
            return 1
        elif value_str == '2':
            return -2
        elif value_str in ['J', 'Q']:
            return 10
        elif value_str == 'K':
            return 0
        else:
            try:
                return int(value_str)
            except ValueError:
                return 0

    def display_final_scores(self, winner: str = None):
        print("\n=== Final Scores ===")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        if self.name in self.scores:
            print(f"Your final score: {self.scores[self.name]}")
        if winner:
            print(f"\nThe winner is {winner}!")
        print("="*30)

    def run(self):
        self.start_listening()
        print("Welcome to the Card Game!")
        self.show_help()
        try:
            while self.running:
                if not self.in_game:
                    command = input("\nEnter command (type 'help' for options): ").strip().lower()
                    if command == 'register':
                        self.register()
                    elif command == 'query_players':
                        self.query_players()
                    elif command == 'query_games':
                        self.query_games()
                    elif command == 'start_game':
                        self.start_game()
                    elif command == 'de_register':
                        self.de_register()
                    elif command == 'help':
                        self.show_help()
                    elif command == 'exit':
                        if self.name:
                            self.de_register()
                        print("Exiting the game. Goodbye!")
                        self.running = False
                        break
                    else:
                        print("Invalid command. Type 'help' to see available commands.")
                else:
                    with self.lock:
                        if self.is_my_turn:
                            self.play_turn()
                            self.is_my_turn = False  # Reset the flag after the turn
                    time.sleep(0.1)  # Sleep briefly to prevent CPU overuse
        except KeyboardInterrupt:
            self.shutdown()

    def show_help(self):
        help_text = """
=== Available Commands ===
register         - Register with the tracker
query_players    - List all registered players
query_games      - List all active games
start_game       - Start a new game
de_register      - Deregister from the tracker
help             - Show this help message
exit             - Exit the application
=========================
"""
        print(help_text)

    def shutdown(self):
        logging.info("Shutting down player...")
        self.running = False
        self.t_sock.close()
        self.p_sock.close()
        if hasattr(self, 'listener_thread') and self.listener_thread.is_alive():
            self.listener_thread.join()
        logging.info("Player has been shut down gracefully.")

if __name__ == '__main__':
    if len(sys.argv) != 6:
        print("Usage: python player.py <tracker_ip> <tracker_port> <t_port> <p_port> <group_number>")
        sys.exit(1)

    tracker_ip = sys.argv[1]
    tracker_port = int(sys.argv[2])
    t_port = int(sys.argv[3])
    p_port = int(sys.argv[4])
    group_number = int(sys.argv[5])

    player = Player(tracker_ip, tracker_port, t_port, p_port, group_number)
    player.run()
