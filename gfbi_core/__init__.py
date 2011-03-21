# Needed by gitbuster
NAMES = {'actor':'Actor', 'author':'Author',
         'authored_date':'Authored Date', 'committed_date':'Committed Date',
         'committer':'Committer', 'count':'Count', 'diff':'Diff',
         'diffs':'Diffs', 'find_all':'Find All', 'hexsha':'Id',
         'lazy_properties':'Lazy Properties',
         'list_from_string':'List From String', 'message':'Message',
         'parents':'Parents', 'repo':'Repo', 'stats':'Stats',
         'summary':'Summary', 'tree':'Tree'}

NOT_EDITABLE_FIELDS = ['hexsha',]

ENV_FIELDS = {'author_name'     : 'GIT_AUTHOR_NAME',
              'author_email'    : 'GIT_AUTHOR_EMAIL',
              'authored_date'   : 'GIT_AUTHOR_DATE',
              'committer_name'  : 'GIT_COMMITTER_NAME',
              'committer_email' : 'GIT_COMMITTER_EMAIL',
              'committed_date'  : 'GIT_COMMITTER_DATE' }

TEXT_FIELDS = ['message', 'summary']
ACTOR_FIELDS = ['author', 'committer']
TIME_FIELDS = ['authored_date', 'committed_date']
