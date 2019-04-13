import sys, getopt
import socket


#0..2^m-1
m = 1 # if m = 1, keyspace is 0,1
keyspace_max = 2^m-1 
'''
def recv_packet(c_sock):
    testdata = c_sock.recv(1)
    if not testdata:
        return ""
    packet_size = testdata.decode('utf-8') # pick the first 1 byte (normal size of chars)
    #print(packet_size)
    while "%" not in packet_size:
        packet_size += c_sock.recv(1).decode('utf-8') # recieve 1 byte every time
        #print(packet_size)

    packet_size = int(packet_size[:-1])
    packet = c_sock.recv(packet_size).decode('utf-8')
    return packet
'''

#each file is stored as the value in a key,value pair at the destined node
def fileHash(filename):
	# temporary file naming convention is "filen.txt", where n = file number, 0,1,2..
	key = stringHasher(filename)
	return key # m bit unsigned integer

# used for hashing both node names and file names
def stringHasher(s):
	return name

# there must be a Node class, of which an instance is created in the main
class Node():
	def __init__(self):
		self.ip = "192.168.0.101"
		self.port = 5100
		self.name = ip+':'+port # distinct name
		self.hashedName = stringHasher(s=name) # hash this name
		self.id = 0
		# every node itself also participates as a key store
		self.keystorage = {} # key, file_name pairs for every file stored at this node
		self.finger_table = {} # for every node there will be a finger table as a dictionary of successors
		print("Node object created.")

	def send_file(self): # parameter for who to send to
		# header will have the packet length of the data being sent
		fileHandler = open("file1.txt", "r")
		file_data = fileHandler.read()
		fileHandler.close()
		header = 13 #length of packet, characters = 1 byte for each
		sending_data = str(header) + '%' + file_data # % is a separator, not counted
		print(f"Sending {sending_data}")
		#send

	#remember self is also an argument
	def recv_file(self): # parameter for who to recv from
		# file will be recieved as text string and stored as .txt
		'''
		recieved_data = recv_packet() # from recv function of socket
		fileHandler = open(self.filename, "w")
		fileHandler.write(recieved_data)
		fileHandler.close()
		'''

	# Chord efficiently adapts as a node joins/leaves the system
	def join(self):
		print("Joined the network.")

	def stabilize(self):
		print("Stabilzing the network.")

	def leave(self):
		print("Formally leaving the network.")

	#can answer queries even if the system is changing constantly
	def lookup(self, filename):
		print("Answer query.")
		#hash given filename to get its key, and then check where that key is stored on the network, forward request to that node

	def get_hashedName(self):
		# take hash of the given name
		return get_hashedName

def main(argv):
	#script for every node, main thing, whenever a node script is run, it goes online, connects to the network
	print("Instantiating node.")
	new_node = Node()
	new_node.join()
	new_node.send_file()
	new_node.leave()
	


if __name__ == '__main__':
    main(sys.argv[1:])
