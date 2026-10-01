def colors_of(program: str) -> tuple[str | None, str | None]:
    """条件付き書式に対応する (背景色, 文字色) を返す。"""
    match program.casefold():
        case p if p.startswith("8th sp"):
            return "#000000", "#FFFFFF"
        case p if p.startswith("9th sp"):
            return "#000000", "#FFFFFF"
        case p if p.startswith("10th sp"):
            return "#000000", "#FFFFFF"
        case p if p.startswith("april feel"):
            return "#FF9933", "#000000"
        case p if p.startswith("beercycle"):
            return "#7A3202", "#FFFFFF"
        case p if p.startswith("feel deep"):
            return "#FFFFFF", "#000000"
        case p if p.startswith("feel high"):
            return "#FFFFFF", "#000000"
        case p if p.startswith("l 24 feel"):
            return "#00121C", "#3399FF"
        case p if p.startswith("l 24 free"):
            return "#00121C", "#FF3333"
        case p if p.startswith("l 25 btm"):
            return "#00121C", "#BD47DC"
        case p if p.startswith("l 25 feel"):
            return "#00121C", "#3399FF"
        case p if p.startswith("l 25 free"):
            return "#00121C", "#FF3333"
        case p if p.startswith("live event"):
            return "#000000", "#c2a53e"
        case p if p.startswith("bb1"):
            return "#FFFF66", "#000000"
        case p if p.startswith("bb2"):
            return "#FF9933", "#000000"
        case p if p.startswith("bb3"):
            return "#FF3300", "#000000"
        case p if p.startswith("bsbi"):
            return "#336699", "#FFFF66"
        case p if p.startswith("bswi"):
            return "#990099", "#FFFF66"
        case p if p.startswith("bsb"):
            return "#00CCFF", "#000000"
        case p if p.startswith("bsw"):
            return "#CC66FF", "#FFFFFF"
        case p if p.startswith("bsl"):
            return "#0000CC", "#FFFFFF"
        case p if p.startswith("feel now g"):
            return "#B08A3A", "#FFFFFF"
        case p if p.startswith("feel now b"):
            return "#00121C", "#FFFFFF"
        case p if p.startswith("feel now s"):
            return "#666666", "#FFFFFF"
        case p if p.startswith("skrillex"):
            return "#FFFFFF", "#000000"
        case _:
            return None, None
