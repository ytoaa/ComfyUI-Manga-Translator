"""Build the bundled static fallback from the pinned, OFL-licensed Noto Sans KR font.

No network access. Obtain the source from the URL in lettering/fonts/sources.json.
Requires fontTools; normal plugin execution never runs this tool.
"""
import argparse
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE_BLOB='b386890ba945e1f39448a6b59f20c5d194f58808'


def build(source, destination):
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    data=Path(source).read_bytes()
    if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=SOURCE_BLOB:
        raise ValueError('Fallback font source differs from pinned upstream Git blob')
    font=TTFont(source,recalcTimestamp=False)
    font=instantiateVariableFont(font,{'wght':400},inplace=True)
    values={1:'MangaSansKR Fallback',2:'Regular',3:'MangaSansKR-Fallback-400-1',
            4:'MangaSansKR Fallback Regular',6:'MangaSansKR-Fallback',
            16:'MangaSansKR Fallback',17:'Regular'}
    for record in font['name'].names:
        if record.nameID in values:
            record.string=values[record.nameID].encode(record.getEncoding())
    # Preserve upstream copyright and OFL name records; rename the derived family.
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    font.save(destination,reorderTables=True);font.close()
    print(destination,destination.stat().st_size,hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--destination',default=str(ROOT/'lettering/fonts/MangaSansKR-Fallback.ttf'))
    args=parser.parse_args();build(args.source,args.destination)
