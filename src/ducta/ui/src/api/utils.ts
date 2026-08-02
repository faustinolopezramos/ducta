import { StorageService } from "../utils/storage";

export const sourceKey = (): string => StorageService.getSource() ?? "__default__";
