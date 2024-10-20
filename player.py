# player.py

import socket
import json
import threading
import sys
import random
import os
import time
from common import User, Game  # Ensure 'common.py' defines User and Game classes appropriately

TRACE = False  # Set to True to enable debug tracing

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

class Card:
    def __init__(self, value):
        self.value = value  # e.g., 'A♠', '10♥', 'K♦'

    def __repr__(self):
        return self.value

class Deck:
    def __init__(self):
        suits = ['♣', '♦', '♥', '♠']
        values = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        self.cards = [Card(f"{v}{s}") for s in suits for v in values]
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

class Player:
    def __init__(self, tracker_ip, tracker_port, t_port, p_port, group_number):
        self.tracker_ip = tracker_ip
        self.tracker_port = tracker_port
        self.t_port = t_port
        self.p_port = p_port
        self.group_number = group_number
        self.name = None
        self.hand = []
        self.score = 0
        self.t_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.t_sock.bind(('', self.t_port))
        except OSError as e:
            print(f"Error binding t_port {self.t_port}: {e}")
            sys.exit(1)
        self.p_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.p_sock.bind(('', self.p_port))
        except OSError as e:
            print(f"Error binding p_port {self.p_port}: {e}")
            sys.exit(1)
        self.players_info = []
        self.game_id = None
        self.holes = 0
        self.is_dealer = False
        self.stock_pile = []
        self.discard_pile = []
        self.hand_grid = []
        self.card_statuses = []
        self.current_player_index = 0
        self.game_over = False
        self.lock = threading.Lock()
        self.dealer_info = None
        self.scores = {}
        self.running = True
        self.players_done = set()
        self.in_game = False

        # Flags and data for thread communication
        self.is_my_turn = False
        self.turn_data = {}
        self.steal_event = threading.Event()
        self.steal_response = {}
        self.steal_lock = threading.Lock()

        # Initialize turn_event for synchronization
        self.turn_event = threading.Event()

        # Variables to track holes
        self.current_hole = 0
        self.hole_over = False

        # Calculate the port range based on the group number
        self.port_min, self.port_max = self.calculate_port_range(group_number)

        if not (self.port_min <= self.t_port <= self.port_max) or not (self.port_min <= self.p_port <= self.port_max):
            print(f"Port numbers must be in the range {self.port_min}-{self.port_max} for group {self.group_number}")
            sys.exit(1)

        # Initialize set to keep track of received scores
        self.scores_received = set()

    def calculate_port_range(self, group_number):
        base_port = ((group_number - 1) // 2) * 1000 + (1000 if group_number % 2 == 0 else 1500)
        port_min = base_port
        port_max = base_port + 499
        return port_min, port_max

    def trace(self, message):
        if TRACE:
            print(f"[TRACE] {message}")

    def get_local_ip(self):
        """Retrieve the local IP address of the machine."""
        try:
            # Connect to a public DNS server to get the local IP address
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            print(f"Error obtaining local IP: {e}")
            return "127.0.0.1"  # Fallback to localhost

    def send_message(self, msg, ip, port, expect_response=False, timeout=5):
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
            print("No response from server. Please try again later.")
        except Exception as e:
            print(f"Error communicating with {ip}:{port}: {e}")
        finally:
            sock.settimeout(None)
        return None

    def send_to_tracker(self, msg):
        return self.send_message(msg, self.tracker_ip, self.tracker_port, expect_response=True)

    def register(self):
        if self.name:
            print("You are already registered.")
            return
        self.name = input("Enter your username: ").strip()
        if not self.name:
            print("Username cannot be empty.")
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

    def display_players(self, players):
        clear_screen()
        print(f"{Colors.BOLD}{Colors.BLUE}=== Player List ({len(players)} players) ==={Colors.RESET}")
        print(f"{'Username':<15}{'IP':<15}{'T-Port':<10}{'P-Port':<10}{'State':<10}")
        print("-" * 60)
        for player in players:
            print(f"{player['username']:<15}{player['ip']:<15}{player['t_port']:<10}{player['p_port']:<10}{player['state']:<10}")
        print("-" * 60)

    def display_games(self, games):
        clear_screen()
        print(f"{Colors.BOLD}{Colors.BLUE}=== Game List ({len(games)} games) ==={Colors.RESET}")
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
            print("Game started successfully. Players have been notified.")
        else:
            print(f"Failed to start game: {response.get('message', '') if response else ''}")

    def get_numeric_input(self, prompt, min_value, max_value):
        try:
            value = int(input(prompt))
            if min_value <= value <= max_value:
                return value
            else:
                print(f"Value must be between {min_value} and {max_value}.")
        except ValueError:
            print("Invalid input.")
        return None

    def start_listening(self):
        if not hasattr(self, 'listener_thread') or not self.listener_thread.is_alive():
            self.listener_thread = threading.Thread(target=self.listen_for_player_messages, daemon=True)
            self.listener_thread.start()

    def listen_for_player_messages(self):
        while not self.game_over and self.running:
            try:
                data, addr = self.p_sock.recvfrom(65535)
                msg = json.loads(data.decode())
                command = msg.get('command', '')
                self.trace(f"Received message from {addr}: {msg}")
                handler = getattr(self, f"handle_{command}", None)
                if handler:
                    handler(msg, addr)
                else:
                    print(f"Unknown command received: {command}")
            except Exception as e:
                self.trace(f"Error in listen_for_player_messages: {e}")

    def handle_assigned_game(self, msg, addr):
        game_id = msg.get('game_id')
        dealer_info = msg.get('dealer')
        players = msg.get('players', [])
        holes = msg.get('holes', 0)

        # Validation
        if game_id is None or dealer_info is None or not players or holes <= 0:
            self.trace("Invalid assigned_game message received.")
            return

        with self.lock:
            self.game_id = game_id
            self.holes = holes
            self.players_info = [User(**player) for player in players]
            self.dealer_info = User(**dealer_info) if dealer_info else None
            self.is_dealer = (self.name == self.dealer_info.username)
            # Initialize cumulative scores
            self.scores = {player.username: 0 for player in self.players_info}
            self.score = 0
            self.players_done = set()
            self.game_over = False
            self.in_game = True  # Important: Set in_game to True

        clear_screen()
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Assigned to Game {self.game_id} ==={Colors.RESET}")
        print(f"Dealer: {Colors.CYAN}{self.dealer_info.username}{Colors.RESET}")
        print(f"Players: {[player.username for player in self.players_info]}")
        print(f"Holes: {self.holes}")

        if self.is_dealer:
            # If the player is the dealer, initiate the game setup
            threading.Thread(target=self.play_game, daemon=True).start()
        else:
            # If not the dealer, wait for the dealer to send hands
            print("Waiting for the dealer to distribute hands...")

    def play_game(self):
        if self.is_dealer:
            threading.Thread(target=self.manage_turns, daemon=True).start()
        else:
            pass  # Non-dealer players wait for their turns

    def send_hand(self, player, hand):
        msg = {
            'command': 'send_hand',
            'hand': [card.value for card in hand],
            'dealer_info': self.dealer_info.to_dict()
        }
        self.send_message(msg, player.ip, player.p_port)

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
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== {self.name}'s Hand ==={Colors.RESET}")
        for row in range(2):
            row_display = ""
            for col in range(3):
                card = self.hand_grid[row][col]
                if self.card_statuses[row][col]:
                    row_display += self.format_card(card.value) + " "
                else:
                    row_display += self.format_card("??") + " "
            print(row_display)
        print(f"\n{Colors.YELLOW}Discard Pile Top Card:{Colors.RESET} {self.format_card(self.discard_pile[-1].value) if self.discard_pile else 'Empty'}")
        print("=" * 30)

    def format_card(self, card_value):
        suit_symbols = {'S': '♠', 'H': '♥', 'D': '♦', 'C': '♣'}
        if card_value == "??":
            return f"{Colors.BOLD}{Colors.RED}[ ?? ]{Colors.RESET}"
        value = card_value[:-1]
        suit = card_value[-1]
        suit_symbol = suit if suit in '♠♥♦♣' else suit_symbols.get(suit, '?')
        color = Colors.RED if suit_symbol in ['♥', '♦'] else Colors.BLUE
        return f"{color}[{value}{suit_symbol}]{Colors.RESET}"

    def print_full_hand(self):
        """Print the hand with all cards revealed."""
        clear_screen()
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== {self.name}'s Final Hand ==={Colors.RESET}")
        for row in range(2):
            row_display = ""
            for col in range(3):
                card = self.hand_grid[row][col]
                row_display += self.format_card(card.value) + " "
            print(row_display)
        print("=" * 30)

    def handle_send_hand(self, msg, addr):
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

    def handle_your_turn(self, msg, addr):
        with self.lock:
            self.stock_pile = [Card(val) for val in msg.get('stock_pile', [])]
            self.discard_pile = [Card(val) for val in msg.get('discard_pile', [])]
            self.current_player_index = msg.get('current_player_index', 0)
            self.is_my_turn = True
            self.turn_data = msg  # Store any additional data if needed
        self.trace(f"Updated stock_pile and discard_pile for turn.")

    def handle_update_piles(self, msg, addr):
        with self.lock:
            self.stock_pile = [Card(val) for val in msg.get('stock_pile', [])]
            self.discard_pile = [Card(val) for val in msg.get('discard_pile', [])]
        self.print_hand()

    def handle_end_game(self, msg, addr):
        self.game_over = True
        self.in_game = False
        print("\nGame ended!")
        self.print_full_hand()  # Reveal all cards
        # Receive the final scores
        if 'scores' in msg:
            self.scores = msg['scores']
            winner = msg.get('winner', '')
            self.display_final_scores(winner)
        else:
            print("Failed to receive final scores.")

    def handle_update_player_state(self, msg, addr):
        with self.lock:
            self.current_player_index = msg.get('current_player_index', 0)
            players = msg.get('players', [])
            if players:
                self.players_info = [User(**player) for player in players]
        self.trace(f"Updated current_player_index to {self.current_player_index}")

    def handle_turn_over(self, msg, addr):
        if self.is_dealer:
            self.turn_event.set()
            self.trace("Turn event set by 'turn_over'.")
        else:
            self.trace(f"Received turn_over from {addr}, but not the dealer.")

    def handle_steal_card(self, msg, addr):
        from_player = msg.get('from_player')
        position = msg.get('position')  # Extract desired position from the message
        if position and isinstance(position, list) and len(position) == 2:
            i, j = position
            if 0 <= i < 2 and 0 <= j < 3:
                with self.lock:
                    if self.card_statuses[i][j]:
                        stolen_card = self.hand_grid[i][j]
                        self.hand_grid[i][j] = Card("??")  # Replace stolen card with face-down card
                        self.card_statuses[i][j] = False
                        response = {'command': 'steal_response', 'card': stolen_card.value}
                        print(f"{from_player} stole your {self.format_card(stolen_card.value)} from position ({i}, {j}).")
                        self.print_hand()
                    else:
                        response = {'command': 'steal_response', 'card': None}
                        print(f"{from_player} attempted to steal from an empty or face-down position ({i}, {j}).")
            else:
                response = {'command': 'steal_response', 'card': None}
                self.trace("Invalid position received in steal_card.")
        else:
            response = {'command': 'steal_response', 'card': None}
            self.trace("Invalid steal_card message received.")

        self.send_message(response, addr[0], addr[1])

    def handle_steal_response(self, msg, addr):
        with self.steal_lock:
            self.steal_response = msg
            self.steal_event.set()

    def handle_swap_card(self, msg, addr):
        swapped_card_value = msg.get('card')
        position = msg.get('position')
        if swapped_card_value and position and isinstance(position, list) and len(position) == 2:
            i, j = position
            if 0 <= i < 2 and 0 <= j < 3:
                with self.lock:
                    self.hand_grid[i][j] = Card(swapped_card_value)
                    self.card_statuses[i][j] = True
                print(f"Received swapped card {self.format_card(swapped_card_value)} at position ({i}, {j}).")
                self.print_hand()
            else:
                self.trace("Invalid position received in swap_card.")
        else:
            self.trace("Invalid swap_card message received.")

    def handle_send_score(self, msg, addr):
        self.calculate_score()  # Calculate the current score before sending
        self.send_score(addr)

    def handle_score_response(self, msg, addr):
        player_name = msg.get('player')
        player_score = msg.get('score', 0)
        with self.lock:
            if player_name in self.scores:
                self.scores[player_name] += player_score  # Accumulate scores
            else:
                self.scores[player_name] = player_score
            if self.is_dealer:
                self.scores_received.add(player_name)  # Add player's name to scores_received

    def handle_player_done(self, msg, addr):
        player_name = msg.get('player')
        with self.lock:
            self.players_done.add(player_name)
            if self.is_dealer and self.check_hole_end():
                self.hole_over = True

    def handle_end_hole(self, msg, addr):
        # Handle end of hole message from the dealer
        self.scores = msg.get('scores', self.scores)
        self.display_current_scores()
        self.hole_over = True

    def manage_turns(self):
        # Initialize cumulative scores
        self.scores = {player.username: 0 for player in self.players_info}
        for hole in range(1, self.holes + 1):
            self.current_hole = hole
            print(f"\n{Colors.BOLD}{Colors.GREEN}=== Starting Hole {hole}/{self.holes} ==={Colors.RESET}")
            self.setup_hole()
            self.players_done = set()
            self.hole_over = False
            while not self.hole_over and self.running:
                current_player = self.players_info[self.current_player_index]
                print(f"\nIt's {Colors.CYAN}{current_player.username}{Colors.RESET}'s turn.")
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

                self.turn_event.wait()
                self.turn_event.clear()
                if self.check_hole_end():
                    self.hole_over = True
                    break
                with self.lock:
                    self.current_player_index = (self.current_player_index + 1) % len(self.players_info)
                self.update_player_state()
            # End of hole
            self.end_hole()
            if not self.running:
                break
        # After all holes, declare the winner
        self.declare_winner()

    def setup_hole(self):
        # Dealer sets up the game for the hole
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
        if not self.stock_pile:
            self.trace("Stock pile is empty after dealing.")
        top_card = self.stock_pile.pop()
        self.discard_pile = [top_card]
        self.current_player_index = 0
        self.update_piles()
        self.update_player_state()

    def check_hole_end(self):
        with self.lock:
            # Hole ends when any player is done (can be modified as per game rules)
            return len(self.players_done) >= 1

    def end_hole(self):
        self.calculate_score()
        print(f"\nScore for {self.name} in hole {self.current_hole}: {self.score}")
        if self.is_dealer:
            with self.lock:
                self.scores[self.name] += self.score  # Accumulate dealer's own score
            self.scores_received = set([self.name])  # Include dealer's own name
            for player in self.players_info:
                if player.username != self.name:
                    msg = {'command': 'send_score'}
                    self.send_message(msg, player.ip, player.p_port)
            # Wait for all scores to be collected
            while len(self.scores_received) < len(self.players_info):
                time.sleep(0.1)
            # Send end_hole message with current scores
            end_hole_msg = {
                'command': 'end_hole',
                'scores': self.scores
            }
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(end_hole_msg, player.ip, player.p_port)
            # Display current scores
            self.display_current_scores()
            # Display results for 10 seconds before proceeding
            print(f"\nNext hole will start in 10 seconds...")
            time.sleep(10)
            self.hole_over = True
        else:
            self.send_score((self.dealer_info.ip, self.dealer_info.p_port))
            # Wait for hole_over signal
            while not self.hole_over and self.running:
                time.sleep(0.1)
            # Display results for 10 seconds before proceeding
            print(f"\nNext hole will start in 10 seconds...")
            time.sleep(10)
        if self.running:
            self.reset_for_next_hole()

    def reset_for_next_hole(self):
        # Reset game state for the next hole
        self.hand = []
        self.hand_grid = []
        self.card_statuses = []
        self.stock_pile = []
        self.discard_pile = []
        self.is_my_turn = False
        self.turn_data = {}
        self.players_done = set()
        self.game_over = False
        self.hole_over = False
        if self.current_hole < self.holes:
            if self.is_dealer:
                self.setup_hole()
            else:
                print(f"Waiting for dealer {self.dealer_info.username} to start next hole...")
        else:
            self.game_over = True

    def send_score(self, addr):
        msg = {'command': 'score_response', 'player': self.name, 'score': self.score}
        self.send_message(msg, addr[0], addr[1])

    def declare_winner(self):
        winner = min(self.scores, key=self.scores.get)
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Final Scores ==={Colors.RESET}")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        print(f"{Colors.BOLD}{Colors.YELLOW}\nThe winner is {winner}!{Colors.RESET}")
        end_game_msg = {
            'command': 'end_game',
            'scores': self.scores,
            'winner': winner
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(end_game_msg, player.ip, player.p_port)
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
        self.trace(f"Calculated score: {self.score}")  # Debug statement

    def card_value(self, card_str):
        value_str = card_str[:-1]
        if value_str == 'A':
            return 1
        elif value_str == '2':
            return -2
        elif value_str in ['J', 'Q']:
            return 10
        elif value_str == 'K':
            return 0
        elif value_str.isdigit():
            return int(value_str)
        else:
            return 0

    def display_current_scores(self):
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Current Cumulative Scores After Hole {self.current_hole} ==={Colors.RESET}")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        if self.name in self.scores:
            print(f"Your cumulative score: {self.scores[self.name]}")
        print("=" * 30)

    def display_final_scores(self, winner=None):
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Final Scores ==={Colors.RESET}")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        if self.name in self.scores:
            print(f"Your final score: {self.scores[self.name]}")
        if winner:
            print(f"{Colors.BOLD}{Colors.YELLOW}\nThe winner is {winner}!{Colors.RESET}")
        print("=" * 30)

    def play_turn(self):
        self.print_hand()
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== {self.name}'s Turn ==={Colors.RESET}")
        if self.discard_pile:
            print(f"{Colors.YELLOW}Discard Pile Top Card:{Colors.RESET} {self.format_card(self.discard_pile[-1].value)}")
        else:
            print("Discard Pile is empty.")
        print("\nChoose an action:")
        print(f"{Colors.CYAN}1{Colors.RESET}. Draw from Stock")
        print(f"{Colors.CYAN}2{Colors.RESET}. Draw from Discard")
        print(f"{Colors.CYAN}3{Colors.RESET}. Steal a Card")
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

    def draw_from_stock(self):
        with self.lock:
            if not self.stock_pile:
                if len(self.discard_pile) > 1:
                    self.stock_pile = self.discard_pile[:-1]
                    self.discard_pile = [self.discard_pile[-1]]
                    random.shuffle(self.stock_pile)
                    self.trace("Re-shuffled discard pile into stock pile.")
                else:
                    print("No cards left to draw.")
                    self.end_turn()
                    return
            drawn_card = self.stock_pile.pop()
        self.handle_drawn_card(drawn_card)

    def draw_from_discard(self):
        with self.lock:
            if not self.discard_pile:
                print("Discard pile is empty.")
                self.end_turn()
                return
            drawn_card = self.discard_pile.pop()
        self.handle_drawn_card(drawn_card)

    def handle_drawn_card(self, drawn_card):
        print(f"You drew {self.format_card(drawn_card.value)}")
        while True:
            print("\nDo you want to:")
            print(f"{Colors.CYAN}1{Colors.RESET}. Swap a card in your hand")
            print(f"{Colors.CYAN}2{Colors.RESET}. Discard the drawn card")
            action = input("Enter your choice (1 or 2): ").strip()
            if action == '1':
                try:
                    self.print_hand()
                    print("Select the card to swap:")
                    row = int(input("Row (0 or 1): "))
                    col = int(input("Column (0, 1, or 2): "))
                    if not (0 <= row < 2 and 0 <= col < 3):
                        print("Invalid row or column.")
                        continue
                    discarded_card = self.hand_grid[row][col]
                    self.hand_grid[row][col] = drawn_card
                    self.card_statuses[row][col] = True
                    with self.lock:
                        self.discard_pile.append(discarded_card)
                    print(f"Swapped {self.format_card(discarded_card.value)} with {self.format_card(drawn_card.value)}")
                    break
                except ValueError:
                    print("Invalid input.")
            elif action == '2':
                with self.lock:
                    self.discard_pile.append(drawn_card)
                print(f"Discarded {self.format_card(drawn_card.value)}")
                break
            else:
                print("Invalid action. Please choose again.")
        self.print_hand()
        self.update_piles()
        if self.is_all_cards_face_up():
            if self.is_dealer:
                with self.lock:
                    self.players_done.add(self.name)
                if self.check_hole_end():
                    self.hole_over = True
            else:
                self.notify_dealer_player_done()
        self.end_turn()

    def is_all_cards_face_up(self):
        return all([status for row in self.card_statuses for status in row])

    def notify_dealer_player_done(self):
        if not self.is_dealer:
            msg = {'command': 'player_done', 'player': self.name}
            self.send_message(msg, self.dealer_info.ip, self.dealer_info.p_port)

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

        # Choose the card position to steal from the target player
        positions = [(i, j) for i in range(2) for j in range(3)]
        print("\nChoose a card position to steal from the target player:")
        for idx, (i, j) in enumerate(positions):
            print(f"{idx + 1}. Row {i}, Column {j}")
        try:
            pos_idx = int(input("Enter the number of the position to steal: ")) - 1
            if not (0 <= pos_idx < len(positions)):
                print("Invalid position selected. Turn skipped.")
                self.end_turn()
                return
            steal_position = positions[pos_idx]
        except ValueError:
            print("Invalid input. Turn skipped.")
            self.end_turn()
            return

        # Send 'steal_card' command to the target player with the desired position
        msg = {
            'command': 'steal_card',
            'from_player': self.name,
            'position': steal_position  # Include desired position in the message
        }
        self.send_message(msg, target_player.ip, target_player.p_port)

        # Initialize event for synchronization
        self.steal_event = threading.Event()
        if self.steal_event.wait(timeout=10):
            with self.steal_lock:
                response = self.steal_response
            stolen_card_value = response.get('card')
            if stolen_card_value is None:
                print(f"{target_player.username} has no face-up card at the specified position to steal.")
                self.end_turn()
                return
            else:
                stolen_card = Card(stolen_card_value)
                print(f"Stole {self.format_card(stolen_card.value)} from {target_player.username}.")

                # Now, choose a position in own hand to place the stolen card
                print("\nChoose a position in your hand to place the stolen card:")
                for idx, (i, j) in enumerate(positions):
                    print(f"{idx + 1}. Row {i}, Column {j}")
                try:
                    place_idx = int(input("Enter the number of the position: ")) - 1
                    if not (0 <= place_idx < len(positions)):
                        print("Invalid position selected. Turn skipped.")
                        # Optionally, return the stolen card to the target player here
                        self.end_turn()
                        return
                    place_position = positions[place_idx]
                except ValueError:
                    print("Invalid input. Turn skipped.")
                    self.end_turn()
                    return

                i, j = place_position
                swapped_card = self.hand_grid[i][j]
                self.hand_grid[i][j] = stolen_card
                self.card_statuses[i][j] = True
                print(f"Swapped {self.format_card(swapped_card.value)} with {self.format_card(stolen_card.value)}.")

                # Send the swapped card back to the target player with the target's original position
                swap_msg = {
                    'command': 'swap_card',
                    'card': swapped_card.value,
                    'position': steal_position  # Place the swapped card back at the target's original position
                }
                self.send_message(swap_msg, target_player.ip, target_player.p_port)

                self.print_hand()
        else:
            print("No response from the target player. Turn skipped.")
        self.end_turn()

    def end_turn(self):
        if self.is_dealer:
            self.turn_event.set()
        else:
            msg = {'command': 'turn_over'}
            self.send_message(msg, self.dealer_info.ip, self.dealer_info.p_port)

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

    def run(self):
        self.start_listening()
        threading.Thread(target=self.input_thread, daemon=True).start()
        while self.running:
            if self.in_game:
                if self.is_my_turn:
                    self.play_turn()
                    with self.lock:
                        self.is_my_turn = False
                else:
                    time.sleep(0.1)
            else:
                time.sleep(0.1)

    def input_thread(self):
        print(f"{Colors.BOLD}{Colors.GREEN}Welcome to the Card Game!{Colors.RESET}")
        self.show_help()
        while self.running and not self.in_game:
            command = input("\nEnter command (type 'help' for options): ").strip().lower()
            self.handle_command(command)

    def handle_command(self, command):
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
        else:
            print("Invalid command. Type 'help' to see available commands.")

    def show_help(self):
        help_text = f"""
{Colors.BOLD}{Colors.BLUE}=== Available Commands ==={Colors.RESET}
{Colors.CYAN}register{Colors.RESET}         - Register with the tracker
{Colors.CYAN}query_players{Colors.RESET}    - List all registered players
{Colors.CYAN}query_games{Colors.RESET}      - List all active games
{Colors.CYAN}start_game{Colors.RESET}       - Start a new game
{Colors.CYAN}de_register{Colors.RESET}      - Deregister from the tracker
{Colors.CYAN}help{Colors.RESET}             - Show this help message
{Colors.CYAN}exit{Colors.RESET}             - Exit the application
{Colors.BLUE}========================={Colors.RESET}
"""
        print(help_text)

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