import requests

url = "https://nubanner.neu.edu/StudentRegistrationSsb/ssb/searchResults/searchResults?txt_subject=CS&txt_courseNumber=7180&txt_term=202710&pageOffset=0&pageMaxSize=10&sortColumn=subjectDescription&sortDirection=asc"

response = requests.request("GET", url, headers = {
  "Cookie": "JSESSIONID=ABCDEF0123456789ABCDEF0123456789; nubanner-cookie=0123456789.12345.1234;"
})

print(response.text)