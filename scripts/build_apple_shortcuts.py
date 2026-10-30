"""
Build the downloadable Apple Shortcuts (static/shortcuts/*.shortcut).

    python scripts/build_apple_shortcuts.py

Needs macOS: Shortcuts only imports signed files, and signing is done by the
`shortcuts sign` command. The files hold no personal data: when someone adds a
shortcut, Shortcuts asks for their key from Settings > Apple Shortcuts.

Each request goes to Railway first. If the reply isn't this app's JSON (every
shortcut reply has a "server" key), the same request goes to Render.

Workouts live in one Notes folder, "Workout Logs". A folder picked in the
Shortcuts editor is stored as an ID that only exists on the author's account,
so the shortcuts find the folder by name instead: they look at the folder of
each recent note. If none is in "Workout Logs", the folder is created (with a
message saying what it is for). Get Workout saves into it; Log Workout offers
only its newest notes.
"""
import copy
import os
import plistlib
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config  # noqa: E402

HOSTS = dict(
    entry.strip().rpartition("=")[::2]
    for entry in Config.DEPLOYMENT_URLS.split(",")
    if entry.strip()
)
PRIMARY, FALLBACK = HOSTS["Railway"].rstrip("/"), HOSTS["Render"].rstrip("/")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "shortcuts")
KEY_QUESTION = "Paste your shortcut key. In Liftbook, open Settings → Integrations → Apple Shortcuts and tap Copy."
OBJ = "￼"  # placeholder Shortcuts uses for a variable inside text

NOTES_APP = {"TeamIdentifier": "0000000000", "BundleIdentifier": "com.apple.Notes", "Name": "Notes"}
WORKOUT_FOLDER = "Workout Logs"
NOTES_SHOWN_FOR_LOGGING = 5
FOLDER_EXPLAINED = (
    f"Your workouts live in the {WORKOUT_FOLDER} folder in Notes. Get Workout saves every workout there, "
    "and Log Workout only logs notes from there. Please keep your workout notes in this folder."
)


def uid():
    return str(uuid.uuid4()).upper()


def ref(u, name):
    return {"OutputUUID": u, "Type": "ActionOutput", "OutputName": name}


def var(name):
    return {"Type": "Variable", "VariableName": name}


def att(r):
    return {"Value": r, "WFSerializationType": "WFTextTokenAttachment"}


def text(s, *refs):
    """Text with variables: each OBJ in s is filled by the next ref."""
    ranges, pos = {}, 0
    for r in refs:
        pos = s.index(OBJ, pos)
        ranges[f"{{{pos}, 1}}"] = r
        pos += 1
    value = {"string": s}
    if ranges:
        value["attachmentsByRange"] = ranges
    return {"Value": value, "WFSerializationType": "WFTextTokenString"}


def act(ident, **params):
    if not ident.startswith(("is.", "com.")):
        ident = "is.workflow.actions." + ident
    return {"WFWorkflowActionIdentifier": ident, "WFWorkflowActionParameters": params}


class Flow:
    def __init__(self):
        self.actions = []

    def add(self, action):
        self.actions.append(action)

    def out(self, ident, name, **params):
        u = uid()
        self.add(act(ident, UUID=u, **params))
        return ref(u, name)

    def set_var(self, name, r):
        self.add(act("setvariable", WFVariableName=name, WFInput=att(r)))

    def get(self, key):
        return self.out("getvalueforkey", "Dictionary Value", WFDictionaryKey=key, WFInput=att(var("Reply")))

    def begin_if(self, r, condition, **extra):
        g = uid()
        self.add(act("conditional", GroupingIdentifier=g, WFControlFlowMode=0, WFCondition=condition,
                     WFInput={"Type": "Variable", "Variable": att(r)}, **extra))
        return g

    def otherwise(self, g):
        self.add(act("conditional", GroupingIdentifier=g, WFControlFlowMode=1))

    def end_if(self, g):
        self.add(act("conditional", GroupingIdentifier=g, WFControlFlowMode=2, UUID=uid()))

    def stop_with_alert(self, message, title=None):
        params = {"WFAlertActionMessage": message, "WFAlertActionCancelButtonShown": False}
        if title:
            params["WFAlertActionTitle"] = title
        self.add(act("alert", **params))
        self.add(act("exit"))

    def ask_for_key(self):
        """Action 0 holds the pasted key (the import question fills it in).
        A whole Log or Retrieve link also works: only the key part is kept."""
        pasted = self.out("gettext", "Text", WFTextActionText="")
        key = self.out(
            "text.replace", "Updated Text", WFInput=text(OBJ, pasted),
            WFReplaceTextRegularExpression=True,
            WFReplaceTextFind=r"^\s*(?:\S*/shortcut/(?:log|pick)/)?([^/?#\s]+)[\s\S]*$",
            WFReplaceTextReplace="$1",
        )
        self.set_var("Key", key)

    def fetch(self, path, *path_refs, form_text=None):
        """Railway, then Render if Railway's reply isn't ours; stop with an alert if neither answers."""
        def request(base):
            params = {"WFURL": text(f"{base}/shortcut/{path}", var("Key"), *path_refs)}
            if form_text:
                params.update(
                    WFHTTPMethod="POST", WFHTTPBodyType="Form",
                    WFFormValues={"Value": {"WFDictionaryFieldValueItems": [{
                        "WFItemType": 0, "WFKey": text("workout_text"), "WFValue": text(OBJ, form_text),
                    }]}, "WFSerializationType": "WFDictionaryFieldValue"},
                )
            self.set_var("Reply", self.out("downloadurl", "Contents of URL", **params))

        def if_reply_not_ours():
            # Read as plain text: reading an HTML error page as a dictionary would stop the shortcut.
            as_text = self.out("detect.text", "Text", WFInput=att(var("Reply")))
            return self.begin_if(as_text, 999, WFConditionalActionString='"server":')

        request(PRIMARY)
        g = if_reply_not_ours()
        request(FALLBACK)
        self.end_if(g)
        g = if_reply_not_ours()
        self.stop_with_alert("Neither Railway nor Render answered. Try again in a minute.",
                             title="Liftbook is not reachable")
        self.end_if(g)

    def stop_unless_ok(self):
        ok = self.get("ok")
        g = self.begin_if({**ok, "Aggrandizements": [
            {"Type": "WFCoercionVariableAggrandizement", "CoercionItemClass": "WFBooleanContentItem"}]}, 4)
        self.otherwise(g)
        self.stop_with_alert(text(OBJ, self.get("error")))
        self.end_if(g)


def find_notes(limit):
    return dict(
        AppIntentDescriptor={**NOTES_APP, "AppIntentIdentifier": "NoteEntity", "ActionRequiresAppInstallation": True},
        WFContentItemSortProperty="Creation Date", WFContentItemSortOrder="Latest First",
        WFContentItemLimitEnabled=True, WFContentItemLimitNumber=float(limit),
    )


def collect_workout_notes(f, limit):
    """Newest notes first; keep those in the workout folder (by name) and remember the folder."""
    notes = f.out("filter.notes", "Notes", **find_notes(limit))
    loop = uid()
    f.add(act("repeat.each", GroupingIdentifier=loop, WFControlFlowMode=0, WFInput=att(notes)))
    folder_of_item = {**var("Repeat Item"), "Aggrandizements": [
        {"Type": "WFPropertyVariableAggrandizement", "PropertyName": "Folder"}]}
    folder_name = f.out("gettext", "Text", WFTextActionText=text(OBJ, folder_of_item))
    g = f.begin_if(folder_name, 4, WFConditionalActionString=WORKOUT_FOLDER)
    f.add(act("appendvariable", WFVariableName="WorkoutNotes", WFInput=att(var("Repeat Item"))))
    f.set_var("Folder", folder_of_item)
    f.end_if(g)
    f.add(act("repeat.each", GroupingIdentifier=loop, WFControlFlowMode=2, UUID=uid()))


def ensure_workout_folder(f, then_stop_with=None):
    """Sets Folder (and WorkoutNotes). Looks at the newest 40 notes, then 400;
    creates the folder if it still isn't found."""
    collect_workout_notes(f, 40)
    g = f.begin_if(var("Folder"), 101)
    collect_workout_notes(f, 400)
    f.end_if(g)
    g = f.begin_if(var("Folder"), 101)
    created = uid()
    f.add(act("com.apple.Notes.CreateFolderLinkAction", UUID=created, name=WORKOUT_FOLDER,
              AppIntentDescriptor={**NOTES_APP, "AppIntentIdentifier": "CreateFolderLinkAction"}))
    f.set_var("Folder", ref(created, "Folder"))
    message = FOLDER_EXPLAINED + (f" {then_stop_with}" if then_stop_with else "")
    f.add(act("alert", WFAlertActionTitle=f"{WORKOUT_FOLDER} folder created", WFAlertActionMessage=message,
              WFAlertActionCancelButtonShown=False))
    if then_stop_with:
        f.add(act("exit"))
    f.end_if(g)


def log_workout():
    f = Flow()
    f.ask_for_key()
    ensure_workout_folder(f, then_stop_with="Write today's workout in a note there, then run Log Workout again.")
    # Offer the newest few (asking for a range longer than the list is an error).
    f.set_var("Offered", var("WorkoutNotes"))
    count = f.out("count", "Count", Input=att(var("WorkoutNotes")), WFCountType="Items")
    g = f.begin_if(count, 2, WFNumberValue=NOTES_SHOWN_FOR_LOGGING)
    f.set_var("Offered", f.out("getitemfromlist", "Items in Range", WFInput=att(var("WorkoutNotes")),
                               WFItemSpecifier="Items in Range", WFItemRangeStart=1,
                               WFItemRangeEnd=NOTES_SHOWN_FOR_LOGGING))
    f.end_if(g)
    note = f.out("choosefromlist", "Selected Item", WFInput=att(var("Offered")),
                 WFChooseFromListActionPrompt="Which workout do you want to log?")
    note_text = f.out("detect.text", "Text", WFInput=att(note))
    f.fetch(f"log/{OBJ}", form_text=note_text)
    f.stop_unless_ok()
    f.add(act("openurl", WFInput=att(f.get("result_url"))))
    return f


def get_workout():
    f = Flow()
    f.ask_for_key()
    ensure_workout_folder(f)
    f.fetch(f"pick/{OBJ}?list=1")
    f.stop_unless_ok()
    session = f.out("choosefromlist", "Selected Item", WFInput=att(f.get("sessions")),
                    WFChooseFromListActionPrompt="Which session?")
    encoded = f.out("urlencode", "URL Encoded Text", WFInput=text(OBJ, session))
    f.fetch(f"pick/{OBJ}?format=json&key={OBJ}", encoded)
    f.stop_unless_ok()
    f.add(act("com.apple.mobilenotes.SharingExtension", UUID=uid(),
              AppIntentDescriptor={**NOTES_APP, "AppIntentIdentifier": "CreateNoteLinkAction"},
              WFCreateNoteInput=text(OBJ, f.get("text")), folder=att(var("Folder"))))
    return f


# Icon colours and symbols from the Shortcuts palette (colour as RGBA; symbol as its glyph code).
GREEN, BLUE = 0x19BD03FF, 0x1B9AF7FF
WEIGHT_LIFTING, NOTE = 0xE99F, 0xE975


def save(name, flow, color, glyph):
    workflow = {
        "WFWorkflowActions": flow.actions,
        "WFWorkflowClientVersion": "4407",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": color, "WFWorkflowIconGlyphNumber": glyph},
        "WFWorkflowTypes": ["WFWorkflowTypeShowInSearch"],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowHasShortcutInputVariables": False,
        "WFQuickActionSurfaces": [],
        "WFWorkflowImportQuestions": [{
            "ActionIndex": 0, "Category": "Parameter", "ParameterKey": "WFTextActionText",
            "DefaultValue": "", "Text": KEY_QUESTION,
        }],
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        unsigned = os.path.join(tmp, f"{name}.wflow")
        with open(unsigned, "wb") as fh:
            plistlib.dump(copy.deepcopy(workflow), fh, fmt=plistlib.FMT_BINARY)
        target = os.path.join(OUT_DIR, f"{name}.shortcut")
        subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", unsigned, "--output", target], check=True)
    print("wrote", os.path.relpath(target))


if __name__ == "__main__":
    save("Log Workout", log_workout(), GREEN, WEIGHT_LIFTING)
    save("Get Workout", get_workout(), BLUE, NOTE)
