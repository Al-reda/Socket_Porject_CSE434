# player.py
import socket
import pickle
import sys
import math

if len(sys.argv) != 6:
    print("Usage: python player.py <tracker_ip> <tracker_port> <t_port> <p_port> <group_number>")
    sys.exit(1)

tracker_ip = sys.argv[1]
tracker_port = int(sys.argv[2])
t_port = int(sys.argv[3])
p_port = int(sys.argv[4])
group_number = int(sys.argv[5])

# Calculate the port range based on the group number
if group_number % 2 == 0:  # Even group number
    base_port = (group_number // 2) * 1000 + 1000
    port_min = base_port
    port_max = base_port + 499
else:  # Odd group number
    base_port = math.ceil(group_number / 2) * 1000 + 500
    port_min = base_port
    port_max = base_port + 499

if not (port_min <= t_port <= port_max) or not (port_min <= p_port <= port_max):
    print(f"Port numbers must be in the range {port_min}-{port_max} for group {group_number}")
    sys.exit(1)


class Player:
    def __init__(self, tracker_ip, tracker_port, t_port, p_port):
        self.tracker_ip = tracker_ip
        self.tracker_port = tracker_port
        self.t_port = t_port
        self.p_port = p_port
        self.name = None
        self.is_registered = False
        self.t_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.t_sock.bind(('', self.t_port))
        self.p_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.p_sock.bind(('', self.p_port))

    def send_to_tracker(self, msg):
        # Log the message being sent
        print(f"\n[Player] Sending to tracker: {msg}")
        self.t_sock.sendto(pickle.dumps(msg), (self.tracker_ip, self.tracker_port))
        data, _ = self.t_sock.recvfrom(65535)
        # Log the response
        try:
            response = pickle.loads(data)
        except (pickle.UnpicklingError, EOFError, UnicodeDecodeError):
            try:
                response = data.decode()
            except UnicodeDecodeError:
                response = data
        print(f"[Player] Received from tracker: {response}")
        return data

    def register(self):
        if self.is_registered:
            print("You are already registered; you cannot register again.")
            return
        self.name = input("Enter your username: ").strip()
        if not self.name:
            print("Username cannot be empty.")
            return
        message = {
            'command': 'register',
            'player': self.name,
            'IPv4': '127.0.0.1',
            't-port': self.t_port,
            'p-port': self.p_port
        }
        response_data = self.send_to_tracker(message)
        if not response_data:
            print("Registration failed: No response from tracker.")
            return

        try:
            response = response_data.decode()
        except UnicodeDecodeError:
            response = pickle.loads(response_data)
        if isinstance(response, str) and response.startswith("SUCCESS"):
            print(f"Registered successfully as {self.name}")
            self.is_registered = True  # Set registration state to True
        else:
            print(f"Registration failed: {response}")

    def query_players(self):
        message = {'command': 'query_players'}
        data = self.send_to_tracker(message)
        if data is None:
            print("Failed to query players due to no response from tracker.")
            return
        try:
            response = pickle.loads(data)
        except (pickle.UnpicklingError, EOFError) as e:
            print(f"Failed to parse response: {e}")
            return

        count = response.get('count', 0)
        players = response.get('players', [])
        print(f"\nNumber of players: {count}")
        if count > 0:
            print(f"{'Username':<15}{'IP':<15}{'T-Port':<10}{'P-Port':<10}{'State':<10}")
            print("-" * 60)
            for player in players:
                try:
                    print(f"{player.username:<15}{player.ip:<15}{player.t_port:<10}{player.p_port:<10}{player.state:<10}")
                except AttributeError as e:
                    print(f"Error accessing player attributes: {e}")
        else:
            print("No players are currently registered.")

    def query_games(self):
        message = {'command': 'query_games'}
        data = self.send_to_tracker(message)
        if data is None:
            print("Failed to query games due to no response from tracker.")
            return
        try:
            response = pickle.loads(data)
        except (pickle.UnpicklingError, EOFError) as e:
            print(f"Failed to parse response: {e}")
            return

        count = response.get('count', 0)
        print(f"\nNumber of games: {count}")
        if count == 0:
            print("No games are currently available.")
        else:
            print("Game functionality is not implemented in this milestone.")

    def de_register(self):
        message = {
            'command': 'de_register',
            'player': self.name
        }
        response_data = self.send_to_tracker(message)
        if response_data is None:
            print("Failed to de-register due to no response from tracker.")
            return
        try:
            response = response_data.decode()
        except UnicodeDecodeError:
            response = pickle.loads(response_data)
        if isinstance(response, str) and response.startswith("SUCCESS"):
            print(f"De-registered successfully. Bye :) {self.name}!")
            self.is_registered = False  # Reset registration state
            self.name = None
        else:
            print(f"De-registration failed: {response}")

    def run(self):
        while True:
            if not self.is_registered:
                command = input("\nEnter command (register): ").strip().lower()
                if command == 'register':
                    self.register()
                else:
                    print("Invalid command. Please try again.")
            else:
                command = input("\nEnter command (query_players, query_games, de_register): ").strip().lower()
                if command == 'query_players':
                    self.query_players()
                elif command == 'query_games':
                    self.query_games()
                elif command == 'de_register':
                    self.de_register()
                    break  # Exit the loop after de-registration
                else:
                    print("Invalid command. Please try again.")


player = Player(tracker_ip, tracker_port, t_port, p_port)
player.run()