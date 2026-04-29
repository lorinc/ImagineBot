import pickle                                                                                      
from pathlib import Path                                                                                                       
from google_auth_oauthlib.flow import InstalledAppFlow                                                                         

SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/documents.readonly']                       
flow = InstalledAppFlow.from_client_secrets_file('oauth/credentials.json', SCOPES)                                             
creds = flow.run_local_server(port=8081, open_browser=False)                                       
pickle.dump(creds, open('oauth/token.pickle', 'wb'))                                                                           
print('Done. valid=%s' % creds.valid)

