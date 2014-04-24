import email._header_value_parser
from email._header_value_parser import *
from email._header_value_parser import _wsp_splitter, _validate_xtext

## The following is email._header_value_parser.get_unstructured with
## an adaptation: an extra =? parsing step was added:
## if "=?" in tok and not tok.startswith("=?"):
##            tok, rest = tok.split("=?", 1)
##            remainder.insert(0, "=?" + rest)
##
## The code is, as is the rest of python, available under the PSF license.
## See cpython source tree for attribution (bitdancer, haypo, reedy, pjenvey)


def get_unstructured(value):
    """unstructured = (*([FWS] vchar) *WSP) / obs-unstruct
       obs-unstruct = *((*LF *CR *(obs-utext) *LF *CR)) / FWS)
       obs-utext = %d0 / obs-NO-WS-CTL / LF / CR

       obs-NO-WS-CTL is control characters except WSP/CR/LF.

    So, basically, we have printable runs, plus control characters or nulls in
    the obsolete syntax, separated by whitespace.  Since RFC 2047 uses the
    obsolete syntax in its specification, but requires whitespace on either
    side of the encoded words, I can see no reason to need to separate the
    non-printable-non-whitespace from the printable runs if they occur, so we
    parse this into xtext tokens separated by WSP tokens.

    Because an 'unstructured' value must by definition constitute the entire
    value, this 'get' routine does not return a remaining value, only the
    parsed TokenList.

    """
    # XXX: but what about bare CR and LF?  They might signal the start or
    # end of an encoded word.  YAGNI for now, since our current parsers
    # will never send us strings with bare CR or LF.

    unstructured = UnstructuredTokenList()
    while value:
        if value[0] in WSP:
            token, value = get_fws(value)
            unstructured.append(token)
            continue
        if value.startswith('=?'):
            try:
                token, value = get_encoded_word(value)
            except errors.HeaderParseError:
                # XXX: Need to figure out how to register defects when
                # appropriate here.
                pass
            else:
                have_ws = True
                if len(unstructured) > 0:
                    if unstructured[-1].token_type != 'fws':
                        unstructured.defects.append(errors.InvalidHeaderDefect(
                            "missing whitespace before encoded word"))
                        have_ws = False
                if have_ws and len(unstructured) > 1:
                    if unstructured[-2].token_type == 'encoded-word':
                        unstructured[-1] = EWWhiteSpaceTerminal(
                            unstructured[-1], 'fws')
                unstructured.append(token)
                continue
        tok, *remainder = _wsp_splitter(value, 1)
        if "=?" in tok and not tok.startswith("=?"):
            tok, rest = tok.split("=?", 1)
            remainder.insert(0, "=?" + rest)
        vtext = ValueTerminal(tok, 'vtext')
        _validate_xtext(vtext)
        unstructured.append(vtext)
        value = ''.join(remainder)
    return unstructured

email._header_value_parser.get_unstructured = get_unstructured
