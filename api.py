import requests

response = requests.post('http://127.0.0.1:5000/api/summarize', 
                       files={'file': open('C:/Users/user/Desktop/diploma codes/AMM.pdf', 'rb')})
print(response.json())
