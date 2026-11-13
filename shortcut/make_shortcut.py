"""Generate the iPhone Shortcut 「健康同步」 that sends today's Apple Health state to GitHub (repository_dispatch "health").

  python3 shortcut/make_shortcut.py            → dist/健康同步.xml (unsigned plist)
  shortcuts sign --mode anyone -i dist/健康同步.xml -o dist/健康同步.shortcut

The GitHub token is asked for when the shortcut is imported (import question), never stored here.
Sent fields (health_merge.py does the math): sleep_v / sleep_d = stage names and durations of Sleep samples that started
in the last SLEEP_HOURS hours plus sleep_s = their sources, hrv / rhr = today's readings, all lists joined by "|".
Health action format: github.com/viticci/shortcuts-playground-plugin HEALTHKIT.md (observed iOS 26 exports).
"""
import os
import plistlib
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLEEP_HOURS = 16                # run at noon → samples since 20:00 yesterday = last night only
URL = 'https://api.github.com/repos/zhFIsHappy/training-dash/dispatches'
DEBUG = os.environ.get('DEBUG') == '1'  # DEBUG=1 → 「健康同步-调试」: pops up the request and GitHub's reply
HOURS_UNIT, DAYS_UNIT = 32, 16  # NSCalendarUnit, as in iOS exports
OBJ = '￼'                  # placeholder a variable occupies in a text field


def ref(action, name):
    return {'OutputUUID': action['WFWorkflowActionParameters']['UUID'], 'OutputName': name, 'Type': 'ActionOutput'}


def text(*parts):
    """Text field mixing strings and variable refs; ranges count UTF-16 units."""
    s, attach = '', {}
    for p in parts:
        if isinstance(p, str):
            s += p
        else:
            attach[f'{{{len(s.encode("utf-16-le")) // 2}, 1}}'] = p
            s += OBJ
    return {'Value': {'string': s, 'attachmentsByRange': attach}, 'WFSerializationType': 'WFTextTokenString'}


def var(r):
    return {'Value': r, 'WFSerializationType': 'WFTextTokenAttachment'}


def action(ident, **params):
    return {'WFWorkflowActionIdentifier': ident,
            'WFWorkflowActionParameters': {'UUID': str(uuid.uuid4()).upper(), **params}}


def find(kind, date_row, **extra):
    rows = [{'Bounded': True, 'Operator': 4, 'Property': 'Type', 'Removable': False,
             'Values': {'Enumeration': {'Value': kind, 'WFSerializationType': 'WFStringSubstitutableState'}}},
            {'Bounded': True, 'Property': 'Start Date', 'Removable': False, **date_row}]
    return action('is.workflow.actions.filter.health.quantity', WFContentItemFilter={
        'Value': {'WFActionParameterFilterPrefix': 1, 'WFContentPredicateBoundedDate': False,
                  'WFActionParameterFilterTemplates': rows},
        'WFSerializationType': 'WFContentPredicateTableTemplate'}, **extra)


TODAY = {'Operator': 1002, 'Values': {'Number': '7', 'Unit': DAYS_UNIT}}
LAST_NIGHT = {'Operator': 1001, 'Values': {'Number': str(SLEEP_HOURS), 'Unit': HOURS_UNIT}}


def detail(samples, prop):
    return action('is.workflow.actions.properties.health.quantity', WFContentItemPropertyName=prop,
                  WFInput=var(ref(samples, 'Health Samples')))


def joined(a, name):
    return action('is.workflow.actions.text.combine', text=var(ref(a, name)),
                  WFTextSeparator='Custom', WFTextCustomSeparator='|')


def header(k, v):
    return {'WFItemType': 0, 'WFKey': text(k), 'WFValue': v}


def build():
    token = action('is.workflow.actions.gettext', WFTextActionText='')
    sleep = find('Sleep', LAST_NIGHT, WFContentItemSortProperty='Start Date', WFContentItemSortOrder='Oldest First')
    sleep_v, sleep_d, sleep_s = detail(sleep, 'Value'), detail(sleep, 'Duration'), detail(sleep, 'Source')
    sv, sd, ss = joined(sleep_v, 'Value'), joined(sleep_d, 'Duration'), joined(sleep_s, 'Source')
    hrv = find('Heart Rate Variability', TODAY)
    hrv_v = detail(hrv, 'Value')
    hv = joined(hrv_v, 'Value')
    rhr = find('Resting Heart Rate', TODAY)
    rhr_v = detail(rhr, 'Value')
    rv = joined(rhr_v, 'Value')
    date = action('is.workflow.actions.format.date', WFDateFormatStyle='Custom', WFDateFormat='Custom',
                  WFDateFormatString='yyyy-MM-dd', WFDate=text({'Type': 'CurrentDate'}))
    r = lambda a: ref(a, 'Combined Text')
    body = action('is.workflow.actions.gettext', WFTextActionText=text(
        '{"event_type":"health","client_payload":{"date":"', ref(date, 'Formatted Date'),
        '","sleep_v":"', r(sv), '","sleep_d":"', r(sd), '","sleep_s":"', r(ss), '","hrv":"', r(hv), '","rhr":"', r(rv), '"}}'))
    post = action('is.workflow.actions.downloadurl', WFURL=text(URL), WFHTTPMethod='POST', WFHTTPBodyType='File',
                  WFFormValues={'Value': {'WFDictionaryFieldValueItems': []}, 'WFSerializationType': 'WFDictionaryFieldValue'},
                  WFRequestVariable=var(ref(body, 'Text')),
                  WFHTTPHeaders={'Value': {'WFDictionaryFieldValueItems': [
                      header('Authorization', text('Bearer ', ref(token, 'Text'))),
                      header('Accept', text('application/vnd.github+json')),
                      header('Content-Type', text('application/json'))]},
                      'WFSerializationType': 'WFDictionaryFieldValue'})
    actions = [token, sleep, sleep_v, sleep_d, sleep_s, sv, sd, ss, hrv, hrv_v, hv, rhr, rhr_v, rv, date, body, post]
    actions.append(action('is.workflow.actions.notification', WFNotificationActionTitle='健康同步 ✓',  # so a timed run is visible
                          WFNotificationActionBody=text('已发送到 GitHub', ref(post, 'Contents of URL'))))
    if DEBUG:  # pop up what was sent and GitHub's reply (empty reply = success)
        actions.append(action('is.workflow.actions.showresult', Text=text(
            '发送:\n', ref(body, 'Text'), '\n\nGitHub 回复(空=成功):\n', ref(post, 'Contents of URL'))))
    return {
        'WFWorkflowActions': actions,
        'WFWorkflowClientVersion': '2700.0.4',
        'WFWorkflowMinimumClientVersion': 900,
        'WFWorkflowMinimumClientVersionString': '900',
        'WFWorkflowName': '健康同步-测试v2' if DEBUG else '健康同步',
        'WFWorkflowIcon': {'WFWorkflowIconGlyphNumber': 59511, 'WFWorkflowIconStartColor': 4282601983},
        'WFWorkflowImportQuestions': [{'ActionIndex': 0, 'Category': 'Parameter', 'DefaultValue': '',
                                       'ParameterKey': 'WFTextActionText',
                                       'Text': '粘贴 GitHub token(github_pat_ 开头)'}],
        'WFWorkflowInputContentItemClasses': [],
        'WFWorkflowOutputContentItemClasses': [],
        'WFWorkflowTypes': [],
        'WFWorkflowHasOutputFallback': False,
    }


if __name__ == '__main__':
    out = os.path.join(ROOT, 'dist', '健康同步-测试v2.xml' if DEBUG else '健康同步.xml')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    plistlib.dump(build(), open(out, 'wb'), fmt=plistlib.FMT_XML)
    print(out)
