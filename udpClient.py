import socket

def main():
	host = '127.0.0.1'
	port = 5001  # UDP - CLIENT PORT HAS TO BE DIFFERENT FROM SERVER
	# was same in TCP

	server_tuple = ('127.0.0.1', 5000)  # server's port 5000 remember
	
	client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	client_sock.bind((host,port)) # UDP - BINDING SOCKET ON CLIENT END TO client itself
	# TCP - There was BINDING ON SERVER END to server itself

	message = input("-> ")
	while message != 'q':
		# SENDTO(data,(host,port))
		client_sock.sendto(message.encode('utf-8'), server_tuple)

		# RECVFROM(BUFFER)
		data_recieved, data_source_addr = client_sock.recvfrom(1024)  # data recieved from client socket of size 1024 from buffer
		data_recieved = data_recieved.decode('utf-8')
		print("Recieved from server " + data_recieved)
		message = input("-> ")

	client_sock.close()

if __name__ == '__main__':
	main()
