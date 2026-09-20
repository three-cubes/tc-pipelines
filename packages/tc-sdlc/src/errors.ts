export class SdlcError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "SdlcError";
    this.code = code;
  }
}
