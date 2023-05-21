import sys
import traceback

from random_structures.generating_functions import Structure_Generator

if __name__ == "__main__" and not sys.flags.interactive:
    try:
        generator = Structure_Generator.from_json_file(
            sys.argv[1], faker=["FR_fr", "Es"]
        )
        repeat = 1 if len(sys.argv) <= 2 else int(sys.argv[2])
        for _ in range(repeat):
            print(generator.generate_json(indent=2, ensure_ascii=False))
            print()

    except BaseException as e:
        print(
            """Usage:
            python payloads.py specif.json [repeat=1]
        """,
        )
        traceback.print_exception(e)
