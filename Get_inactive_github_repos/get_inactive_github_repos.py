import azure.functions as func
from flask import Flask,request,jsonify
import json
import requests
from datetime import timedelta,datetime
import os
from dotenv import load_dotenv
import logging
from applicationinsights import TelemetryClient
import threading


app = Flask(__name__)
load_dotenv()
INSTRUMENTATION_KEY = os.getenv('APPINSIGHTS_INSTRUMENTATIONKEY')
tc = TelemetryClient(INSTRUMENTATION_KEY)

@app.route("/github/get_inactive_repos", methods=['GET'])
def getInactiveRepositories():
    try:    
       
        function_key = os.getenv('FUNCTION_KEY')  
        base = os.getenv('GITHUB_API_URL')
        base_url = f"{base}graphql?code={function_key}"
        github_url = os.getenv('GITHUB_API_URL')
        organization = os.getenv('ORGANIZATION')
        github_token = os.getenv('GITHUB_TOKEN')
        HEADERS = {'Authorization': f'Bearer {github_token}'}
        # condition = request.headers.get('inactive_days')
        condition = os.getenv('Inactive_Days', 365)
        message = {'message':'Header not found'}
        def log_to_application_insights(repo_info):
                tc.track_event('InactiveRepos', repo_info)
                tc.flush()
        if condition is None:
            return jsonify({"error": "inactive_days header is missing"}), 400
        cutoff_date = (datetime.now() - timedelta(days=int(condition))).isoformat()                

        query_template = """
        {{
            search(query: "org:{organization} pushed:<{cutoff_date}", type: REPOSITORY, first: 100, after: "{after_cursor}") {{
                edges {{
                    node {{
                        ... on Repository {{
                            name
                            description
                            url
                            isPrivate
                            pushedAt
                            updatedAt
                            owner {{
                                login
                            }}
                        }}
                    }}
                }}
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
            }}
        }}
        """

        after_cursor = ""
        all_repos = []
        logging.info(f"search repo query - {query_template}")

        while True:
            query = query_template.format(cutoff_date=cutoff_date, organization=organization, after_cursor=after_cursor)
            response = requests.post(base_url, json={'query': query}, headers=HEADERS)
            
            if response.status_code == 200:
                logging.info(f"All the inactive repos are retrived with status code - {response.status_code}")
                result = response.json()
                logging.info(f"Response JSON: {result}")
                repos = result["data"]["search"]["edges"]
                all_repos.extend(repos)

                page_info = result["data"]["search"]["pageInfo"]
                if not page_info["hasNextPage"]:
                    break

                after_cursor = page_info["endCursor"]
            else:
                logging.info(f"Query failed to run by returning code of {response.status_code}. {query}")
                return jsonify(f"Query failed to run by returning code of {response.status_code}. {query}"), 500
    
        inactive_repos = []
        for repo in all_repos: 
            
            url= github_url+"repos/"+ organization +"/"+ repo['node']['name']+"/collaborators"
            logging.info(f"collaborators_url - {url}")

            adminResponse = requests.get(url, headers=HEADERS)
            collaborators = adminResponse.json()
            logging.info(f"Collaborators JSON: {collaborators}")
            admin_usernames = [collaborator['login'] for collaborator in collaborators if collaborator['permissions']['admin']]
            if(repo['node']['description'] == 'null' or repo['node']['description'] is None):
                description = ''
            else:
                description =  repo['node']['description'] 
            pushed_date = repo['node']['pushedAt']    
            url = f"{github_url}repos/{organization}/{repo['node']['name']}?code={function_key}"
            logging.info(f"archieve url - {url}")
            response = requests.get(url, headers=HEADERS)
            logging.info(f"archieve url status_code - {response.status_code}")
            if response.status_code == 200:
                repo_info = response.json()
                logging.info(f"Repo info: {repo_info}")
            else:
                logging.error(f"Failed to retrieve repo info for {repo['node']['name']}. Status code: {response.status_code}")
                continue

            if pushed_date and pushed_date < cutoff_date and repo_info['archived'] == False:      
                repo_info = {
                    'Name': repo['node']['name'],
                    "Url": repo['node']['url'],
                    "Updated": repo['node']['updatedAt'],
                    "Pushed": repo['node']['pushedAt'],
                    "Owner": repo['node']['owner']['login'],
                    "Description":description,
                    "env": base,
                    'application': 'GitHub',
                    'operation': 'InactiveRepos'
                }                                
                inactive_repos.append(repo_info)
                log_to_application_insights(repo_info)

        logging.info(f"Total number of inactive repos fetched: {len(inactive_repos)}")    
        return jsonify(inactive_repos)
      
    except Exception as e:
            logging.error(f"Exception in getting inactive github repo.Error message: {e}")
            return jsonify({'error': f"Oops! Something bad happened. Error: {str(e)}"}), 500


def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    return func.WsgiMiddleware(app.wsgi_app).handle(req, context)

if __name__ == "__main__":
    app.run()